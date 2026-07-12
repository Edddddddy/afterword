const recordBtn = document.getElementById("record-btn");
const stopBtn = document.getElementById("stop-btn");
const statusLine = document.getElementById("status-line");
const timerEl = document.getElementById("timer");
const chunkInfo = document.getElementById("chunk-info");
const resultPanel = document.getElementById("result-panel");
const resultTitle = document.getElementById("result-title");
const resultFiles = document.getElementById("result-files");
const resultPreview = document.getElementById("result-preview");
const errorPanel = document.getElementById("error-panel");
const errorMessage = document.getElementById("error-message");

const MAX_UPLOAD_RETRIES = 3;
const RETRY_BASE_MS = 500;

let sessionId = null;
let mediaStream = null;
let mediaRecorder = null;
let chunkIntervalSeconds = 1800;
let elapsedTimerId = null;
let recordingStartedAt = null;
let chunksUploaded = 0;
let wakeLock = null;
let isStopping = false;
let uploadChain = Promise.resolve();
let pendingStopResolve = null;

function setStatus(message) {
  statusLine.textContent = message;
}

function setError(message) {
  errorPanel.classList.remove("hidden");
  errorMessage.textContent = message;
}

function clearError() {
  errorPanel.classList.add("hidden");
  errorMessage.textContent = "";
}

function formatElapsed(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function updateTimer() {
  if (!recordingStartedAt) return;
  timerEl.textContent = formatElapsed(Date.now() - recordingStartedAt);
}

function pickMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function audioFilename(blob) {
  if (blob.type.includes("mp4")) return "chunk.mp4";
  if (blob.type.includes("ogg")) return "chunk.ogg";
  return "chunk.webm";
}

function createRecorder() {
  const mimeType = pickMimeType();
  const options = mimeType ? { mimeType } : undefined;
  const recorder = new MediaRecorder(mediaStream, options);

  recorder.ondataavailable = (event) => {
    if (!event.data || event.data.size === 0) {
      if (isStopping && pendingStopResolve) {
        pendingStopResolve(null);
        pendingStopResolve = null;
      }
      return;
    }

    if (isStopping) {
      if (pendingStopResolve) {
        pendingStopResolve(event.data);
        pendingStopResolve = null;
      }
      return;
    }

    uploadChunkInBackground(event.data);
  };

  return recorder;
}

async function fetchConfig() {
  const response = await fetch("/api/config");
  if (!response.ok) {
    throw new Error("Failed to load app config");
  }
  const data = await response.json();
  chunkIntervalSeconds = data.chunkIntervalSeconds || 1800;
}

async function requestWakeLock() {
  if (!("wakeLock" in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
    wakeLock.addEventListener("release", () => {
      wakeLock = null;
    });
  } catch {
    wakeLock = null;
  }
}

async function releaseWakeLock() {
  if (wakeLock) {
    try {
      await wakeLock.release();
    } catch {
      // ignore
    }
    wakeLock = null;
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function uploadWithRetry(url, blob, label, { allowFailure = false } = {}) {
  let lastError = null;
  for (let attempt = 1; attempt <= MAX_UPLOAD_RETRIES; attempt += 1) {
    try {
      const formData = new FormData();
      formData.append("audio", blob, audioFilename(blob));
      const response = await fetch(url, { method: "POST", body: formData });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `${label} upload failed`);
      }
      return response.json();
    } catch (error) {
      lastError = error;
      if (attempt < MAX_UPLOAD_RETRIES) {
        setStatus(`${label} failed, retrying (${attempt}/${MAX_UPLOAD_RETRIES})…`);
        await delay(RETRY_BASE_MS * 2 ** (attempt - 1));
      }
    }
  }
  if (allowFailure) {
    return null;
  }
  throw lastError;
}

function enqueueUpload(task) {
  const run = uploadChain.then(task);
  uploadChain = run.catch(() => {});
  return run;
}

function uploadChunkInBackground(blob) {
  const chunkNumber = chunksUploaded + 1;
  enqueueUpload(async () => {
    setStatus(`Uploading chunk ${chunkNumber}…`);
    chunkInfo.textContent = `Uploading chunk ${chunkNumber}…`;
    const result = await uploadWithRetry(
      `/api/sessions/${sessionId}/chunks`,
      blob,
      `Chunk ${chunkNumber}`,
      { allowFailure: true },
    );
    if (result === null) {
      if (!isStopping) {
        setError(`Chunk ${chunkNumber} failed to upload after ${MAX_UPLOAD_RETRIES} attempts.`);
        setStatus("Upload error — still recording");
      }
      return;
    }
    chunksUploaded += 1;
    chunkInfo.textContent = `${chunksUploaded} chunk(s) uploaded`;
    if (!isStopping) {
      setStatus("Recording…");
    }
  });
}

function stopTimers() {
  clearInterval(elapsedTimerId);
  elapsedTimerId = null;
}

function cleanupMedia() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    try {
      mediaRecorder.stop();
    } catch {
      // ignore
    }
  }
  mediaRecorder = null;

  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
}

function showResult(data) {
  resultPanel.classList.remove("hidden");
  if (data.error) {
    setError(data.error);
  }
  resultTitle.textContent = data.title ? `Title: ${data.title}` : "Summary unavailable";
  resultFiles.textContent = [
    data.summaryPath ? `Summary: ${data.summaryPath}` : null,
    data.transcriptPath ? `Transcript: ${data.transcriptPath}` : null,
  ]
    .filter(Boolean)
    .join("\n");
  resultPreview.textContent = data.preview || "";
}

async function finalizeSession(finalBlob) {
  const stopUrl = `/api/sessions/${sessionId}/stop`;

  if (finalBlob && finalBlob.size > 0) {
    return uploadWithRetry(stopUrl, finalBlob, "Final chunk");
  }

  if (chunksUploaded > 0) {
    const response = await fetch(stopUrl, { method: "POST" });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Failed to finalize session");
    }
    return response.json();
  }

  throw new Error(
    "No audio captured. Record for at least a few seconds before stopping.",
  );
}

async function startRecording() {
  clearError();
  resultPanel.classList.add("hidden");
  isStopping = false;
  chunksUploaded = 0;
  uploadChain = Promise.resolve();
  pendingStopResolve = null;

  await fetchConfig();

  const sessionResponse = await fetch("/api/sessions", { method: "POST" });
  if (!sessionResponse.ok) {
    throw new Error("Failed to start backend session");
  }
  const sessionData = await sessionResponse.json();
  sessionId = sessionData.sessionId;

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    throw new Error(
      "Microphone access denied. On macOS, allow microphone access in System Settings → Privacy & Security → Microphone for your browser.",
    );
  }

  await requestWakeLock();

  mediaRecorder = createRecorder();
  mediaRecorder.start(chunkIntervalSeconds * 1000);
  recordingStartedAt = Date.now();
  elapsedTimerId = setInterval(updateTimer, 1000);

  recordBtn.disabled = true;
  stopBtn.disabled = false;
  setStatus("Recording…");
  chunkInfo.textContent = "0 chunks uploaded";
  updateTimer();
}

async function stopRecording() {
  if (!sessionId || isStopping) return;
  isStopping = true;
  stopBtn.disabled = true;
  stopTimers();
  setStatus("Processing…");

  try {
    const finalBlob = await new Promise((resolve) => {
      pendingStopResolve = resolve;
      if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
      } else {
        resolve(null);
        pendingStopResolve = null;
      }
    });

    cleanupMedia();
    await uploadChain;

    setStatus("Uploading final chunk and generating notes…");
    const result = await finalizeSession(finalBlob);
    showResult(result);
    setStatus("Done — files saved to output folder");
  } catch (error) {
    setError(error.message || "Processing failed");
    setStatus("Processing failed");
  } finally {
    await releaseWakeLock();
    recordBtn.disabled = false;
    stopBtn.disabled = true;
    sessionId = null;
    isStopping = false;
    pendingStopResolve = null;
  }
}

recordBtn.addEventListener("click", () => {
  startRecording().catch((error) => {
    setError(error.message || "Failed to start recording");
    setStatus("Ready");
    cleanupMedia();
    releaseWakeLock();
    recordBtn.disabled = false;
    stopBtn.disabled = true;
  });
});

stopBtn.addEventListener("click", () => {
  stopRecording();
});

window.addEventListener("beforeunload", () => {
  cleanupMedia();
  releaseWakeLock();
});

fetch("/api/health")
  .then((response) => {
    if (!response.ok) throw new Error();
    setStatus("Ready");
  })
  .catch(() => {
    setStatus("Backend offline — start the API server first");
    recordBtn.disabled = true;
  });
