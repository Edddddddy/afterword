# Testing & phase validation

Run from the repository root unless noted.

## Environment for automated gates

Use mock providers (no OpenAI key required):

```bash
export TRANSCRIPTION_PROVIDER=mock
export SUMMARIZATION_PROVIDER=mock
export SESSION_DIR=~/.afterword/sessions-test
export OUTPUT_DIR=~/Desktop
export CHUNK_INTERVAL_SECONDS=60
```

## Start backend

```bash
source .venv/bin/activate
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Phase 1 checks

```bash
curl -s http://127.0.0.1:8000/api/health
SESSION_ID=$(curl -s -X POST http://127.0.0.1:8000/api/sessions | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")
test -f ~/.afterword/sessions-test/$SESSION_ID/metadata.json
git grep -i "sk-" && echo FAIL || echo PASS
```

## Phase 2 / 3 API simulation

```bash
# Create minimal fake webm-ish audio blob (>100 bytes for mock transcription)
python3 scripts/make_test_audio.py /tmp/test-chunk.webm

SESSION_ID=$(curl -s -X POST http://127.0.0.1:8000/api/sessions | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")
curl -s -F "audio=@/tmp/test-chunk.webm" http://127.0.0.1:8000/api/sessions/$SESSION_ID/chunks
curl -s -F "audio=@/tmp/test-chunk.webm" http://127.0.0.1:8000/api/sessions/$SESSION_ID/stop
ls ~/Desktop/*-transcript.md ~/Desktop/q2-planning-sync.md
```

## Phase 4 checks

```bash
# Orphan cleanup: create stale session
python3 scripts/create_stale_session.py
# Restart backend and confirm stale dir removed
```

## Full gate script

```bash
bash scripts/validate_all_phases.sh
```
