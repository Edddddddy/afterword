# AGENTS.md

## Cursor Cloud specific instructions

Afterword is a local meeting recorder: a **FastAPI backend** (`backend/`) and a **Vite/vanilla-JS frontend** (`frontend/`). The backend exposes a session/chunk/stop API; the frontend records mic audio in the browser and uploads chunks. Transcription (Whisper) and summarization (GPT) run through pluggable providers. Standard setup/run commands live in `README.md`; test commands live in `docs/TESTING.md`. Notes below are the non-obvious gotchas for this Linux cloud environment (the app itself targets macOS).

### Running services
- Backend: `cd backend && ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`. Config is read from a `.env` file discovered by walking up from the current directory, so running from `backend/` still finds `/workspace/.env`.
- Frontend: `cd frontend && npm run dev` (serves on `5173`, proxies `/api` → `127.0.0.1:8000`).
- The dev `.env` is gitignored. For this VM it should use mock providers (no OpenAI key needed): `TRANSCRIPTION_PROVIDER=mock` and `SUMMARIZATION_PROVIDER=mock`. With real OpenAI, set `OPENAI_API_KEY` and switch both providers to `openai`.

### Non-obvious gotchas
- **Vite binds to IPv6 localhost only.** The dev server listens on `[::1]:5173`, not `127.0.0.1`. Use `http://localhost:5173` (curl to `127.0.0.1:5173` returns nothing). Browsers work fine.
- **Microphone recording does not work on this Linux VM.** The frontend `Record` button uses `getUserMedia`, which has no mic here (and the app is macOS-only by design). To exercise the full record → transcribe → summarize → save-markdown flow, drive the backend API directly (see `docs/TESTING.md`) or run `bash scripts/validate_all_phases.sh`. The browser UI can still be loaded to confirm it reaches the "Ready" state (backend connected).
- **`scripts/validate_all_phases.sh` kills existing backends.** It internally calls `pkill -f "uvicorn app.main:app"` and starts/stops its own server on port 8000, so any backend you already have running will be killed — restart it after the script finishes.
- **Known test false positive:** the script's `1.5 no secrets` check greps the repo for `sk-` and matches the literal `"sk-"` inside the script itself, so it reports 13 passed / 1 failed even on a clean checkout. This is a pre-existing quirk in the check, not a real leaked secret.
- Generated notes are written to `OUTPUT_DIR` (default `.afterword/output` in the project root); session data (chunks, transcript) lives in `SESSION_DIR` (default `.afterword/sessions`). Sessions older than `SESSION_TTL_HOURS` (default 24) are removed on startup.
