# Afterword

Local meeting recorder for **macOS**. Record via microphone, transcribe with OpenAI Whisper, summarize with GPT 5.2, and save markdown notes plus a separate transcript to `.afterword/output`.

## Requirements

- macOS with Chrome or Safari
- Python 3.11+
- Node.js 18+ and pnpm
- OpenAI API key

## Setup

```bash
# Clone and enter the repo
cd afterword

# Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
# Edit .env and set OPENAI_API_KEY

# Frontend
cd frontend
pnpm install
cd ..
```

## Run

Terminal 1 — backend:

```bash
source .venv/bin/activate
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend:

```bash
cd frontend
pnpm run dev
```

Open http://localhost:5173, click **Record**, speak, then **Stop**. Summary and transcript files appear in `.afterword/output`.

## macOS microphone permissions

If recording fails, open **System Settings → Privacy & Security → Microphone** and enable access for your browser.

## Configuration

See `.env.example`. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for production |
| `OPENAI_SUMMARY_MODEL` | `gpt-5.2` | Summarization model |
| `CHUNK_INTERVAL_SECONDS` | `1800` | Upload/transcribe every 30 min |
| `OUTPUT_DIR` | `.afterword/output` | Where markdown files are saved (project root) |
| `SESSION_DIR` | `.afterword/sessions` | Session storage — audio chunks and working transcript (project root) |
| `SESSION_TTL_HOURS` | `24` | Remove sessions older than this on startup |

For automated tests without OpenAI, set `TRANSCRIPTION_PROVIDER=mock` and `SUMMARIZATION_PROVIDER=mock`.

## Known limitations (v1)

- macOS only (Chrome recommended; Safari supported)
- Microphone capture only (no system/remote audio)
- Requires internet and OpenAI API access
- Browser must stay open during recording (tab may be unfocused)

## Testing

See [docs/TESTING.md](docs/TESTING.md) for phase validation commands.
