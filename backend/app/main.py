import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import SessionState, SessionStatus
from app.providers import build_summarization_provider, build_transcription_provider
from app.providers.base import SummarizationProvider, TranscriptionProvider
from app.sessions.manager import SessionError, SessionManager
from app.utils.slug import slugify, unique_file_path

logger = logging.getLogger(__name__)

app = FastAPI(title="Afterword", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_manager = SessionManager()
transcription_provider: TranscriptionProvider | None = None
summarization_provider: SummarizationProvider | None = None


@app.on_event("startup")
async def startup() -> None:
    global transcription_provider, summarization_provider
    settings.resolved_session_dir().mkdir(parents=True, exist_ok=True)
    settings.resolved_output_dir().mkdir(parents=True, exist_ok=True)
    removed = session_manager.sweep_orphaned_sessions()
    if removed:
        logger.info("Startup sweep removed %s orphaned session(s)", removed)
    transcription_provider = build_transcription_provider()
    summarization_provider = build_summarization_provider()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
async def public_config() -> dict[str, int]:
    return {"chunkIntervalSeconds": settings.chunk_interval_seconds}


@app.post("/api/sessions")
async def create_session() -> dict[str, str]:
    session_id = session_manager.create_session()
    return {"sessionId": session_id}


@app.get("/api/sessions/{session_id}/status")
async def session_status(session_id: str) -> dict:
    try:
        metadata = session_manager.read_metadata(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SessionStatus(
        session_id=session_id,
        state=SessionState(metadata.get("state", SessionState.RECORDING.value)),
        chunks_received=metadata.get("chunks_received", 0),
        transcript_length=session_manager.transcript_length(session_id),
        title=metadata.get("title"),
        error=metadata.get("error"),
    ).to_dict()


async def _process_chunk(
    session_id: str,
    data: bytes,
    *,
    extension: str = "webm",
) -> dict:
    if transcription_provider is None:
        raise HTTPException(status_code=503, detail="Transcription provider not ready")

    if len(data) == 0:
        return {"transcribed": False, "message": "Empty audio chunk skipped"}

    if len(data) > settings.max_chunk_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Chunk exceeds {settings.max_chunk_bytes} byte limit",
        )

    chunk_path: Path | None = None
    try:
        chunk_path = session_manager.save_chunk(session_id, data, extension=extension)
        text = await transcription_provider.transcribe(chunk_path)
        if text.strip():
            session_manager.append_transcript(session_id, text)
            return {"transcribed": True, "textLength": len(text)}
        return {"transcribed": False, "message": "No speech detected in chunk"}
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if chunk_path is not None:
            try:
                session_manager.rollback_chunk(session_id, chunk_path)
            except SessionError:
                logger.exception("Failed to rollback chunk for session %s", session_id)
        logger.exception("Transcription failed for session %s", session_id)
        raise HTTPException(status_code=502, detail="Transcription failed") from exc


def _extension_from_upload(audio: UploadFile | None, data: bytes) -> str:
    if audio and audio.filename and "." in audio.filename:
        return audio.filename.rsplit(".", 1)[-1].lower()
    if audio and audio.content_type:
        if "mp4" in audio.content_type:
            return "mp4"
        if "ogg" in audio.content_type:
            return "ogg"
    return "webm"


@app.post("/api/sessions/{session_id}/chunks")
async def upload_chunk(
    session_id: str,
    audio: UploadFile = File(...),
) -> dict:
    try:
        metadata = session_manager.read_metadata(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if metadata.get("state") not in (
        SessionState.RECORDING.value,
        SessionState.PROCESSING.value,
    ):
        raise HTTPException(status_code=409, detail="Session is not accepting chunks")

    data = await audio.read()
    extension = _extension_from_upload(audio, data)
    return await _process_chunk(session_id, data, extension=extension)


def _stop_response_from_metadata(metadata: dict) -> dict:
    transcript_path = metadata.get("transcript_file")
    summary_path = metadata.get("summary_file")
    response = {
        "title": metadata.get("title"),
        "summaryFile": Path(summary_path).name if summary_path else None,
        "summaryPath": summary_path,
        "transcriptFile": Path(transcript_path).name if transcript_path else None,
        "transcriptPath": transcript_path,
        "preview": "",
    }
    if metadata.get("error"):
        response["error"] = metadata["error"]
    return response


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    audio: UploadFile | None = File(None),
) -> dict:
    if summarization_provider is None:
        raise HTTPException(status_code=503, detail="Summarization provider not ready")

    try:
        metadata = session_manager.read_metadata(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    state = metadata.get("state")
    if state == SessionState.COMPLETE.value:
        return _stop_response_from_metadata(metadata)
    if state == SessionState.ERROR.value:
        if metadata.get("transcript_file"):
            return _stop_response_from_metadata(metadata)
        raise HTTPException(
            status_code=400,
            detail="No speech detected. Try recording again closer to the microphone.",
        )
    if state == SessionState.PROCESSING.value:
        raise HTTPException(status_code=409, detail="Session is already being finalized")

    session_manager.update_metadata(session_id, state=SessionState.PROCESSING.value)

    if audio is not None:
        data = await audio.read()
        if data:
            extension = _extension_from_upload(audio, data)
            try:
                await _process_chunk(session_id, data, extension=extension)
            except HTTPException:
                logger.warning(
                    "Final chunk transcription failed for session %s; continuing with existing transcript",
                    session_id,
                )

    transcript = session_manager.read_transcript(session_id)
    if not transcript:
        session_manager.update_metadata(
            session_id,
            state=SessionState.ERROR.value,
            error="No transcript produced from recording",
        )
        raise HTTPException(
            status_code=400,
            detail="No speech detected. Try recording again closer to the microphone.",
        )

    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    output_dir = settings.resolved_output_dir()
    summary_result = None
    summary_error = None

    try:
        summary_result = await summarization_provider.summarize(transcript)
    except Exception as exc:
        logger.exception("Summarization failed for session %s", session_id)
        summary_error = str(exc)

    slug = slugify(summary_result.title if summary_result else "meeting-notes")
    transcript_path = unique_file_path(output_dir, slug, "-transcript.md")
    transcript_content = (
        f"# {summary_result.title if summary_result else 'Meeting'} — Full Transcript\n\n"
        f"Recorded: {recorded_at}\n\n---\n\n{transcript}"
    )
    transcript_path.write_text(transcript_content, encoding="utf-8")

    summary_path: Path | None = None
    preview = ""

    if summary_result:
        summary_path = unique_file_path(output_dir, slug, ".md")
        summary_content = f"# {summary_result.title}\n\n{summary_result.markdown_body}\n"
        summary_path.write_text(summary_content, encoding="utf-8")
        preview = _extract_summary_preview(summary_result.markdown_body)
        session_manager.update_metadata(
            session_id,
            state=SessionState.COMPLETE.value,
            title=summary_result.title,
            summary_file=str(summary_path),
            transcript_file=str(transcript_path),
            error=None,
        )
    else:
        session_manager.update_metadata(
            session_id,
            state=SessionState.ERROR.value,
            title=None,
            transcript_file=str(transcript_path),
            error=f"Summarization failed: {summary_error}",
        )

    if summary_result is None:
        return {
            "title": None,
            "summaryFile": None,
            "summaryPath": None,
            "transcriptFile": transcript_path.name,
            "transcriptPath": str(transcript_path),
            "preview": "",
            "error": f"Summarization failed: {summary_error}",
        }

    return {
        "title": summary_result.title,
        "summaryFile": summary_path.name if summary_path else None,
        "summaryPath": str(summary_path) if summary_path else None,
        "transcriptFile": transcript_path.name,
        "transcriptPath": str(transcript_path),
        "preview": preview,
    }


def _extract_summary_preview(markdown_body: str, max_len: int = 280) -> str:
    for line in markdown_body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            if len(stripped) > max_len:
                return stripped[: max_len - 3] + "..."
            return stripped
    return ""
