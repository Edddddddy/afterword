#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export TRANSCRIPTION_PROVIDER=mock
export SUMMARIZATION_PROVIDER=mock
export SESSION_DIR="${SESSION_DIR:-$HOME/.afterword/sessions-test}"
export OUTPUT_DIR="${OUTPUT_DIR:-$HOME/Desktop}"
export CHUNK_INTERVAL_SECONDS=60
export HOST=127.0.0.1
export PORT=8000

PASS=0
FAIL=0

pass() { echo "✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "❌ $1"; FAIL=$((FAIL + 1)); }

if [ ! -d .venv ]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q -r backend/requirements.txt
else
  source .venv/bin/activate
fi

if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install --silent)
fi

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
}
trap cleanup EXIT

start_server() {
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
  sleep 1
  cd backend
  uvicorn app.main:app --host 127.0.0.1 --port 8000 &
  SERVER_PID=$!
  cd "$ROOT"
  sleep 2
}

# Start backend
start_server

# Phase 1
echo "=== Phase 1 ==="
HEALTH=$(curl -sf http://127.0.0.1:8000/api/health || true)
[[ "$HEALTH" == *"ok"* ]] && pass "1.2 health endpoint" || fail "1.2 health endpoint"

SESSION_JSON=$(curl -sf -X POST http://127.0.0.1:8000/api/sessions)
SESSION_ID=$(echo "$SESSION_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")
META="$SESSION_DIR/$SESSION_ID/metadata.json"
[[ -f "$META" ]] && pass "1.3 session dir created" || fail "1.3 session dir created"
[[ "$SESSION_DIR" == "$HOME/.afterword/sessions-test" ]] && pass "1.4 env expansion" || fail "1.4 env expansion"
git grep -qi "sk-" -- ':!*.example' ':!.env.example' ':!docs/PLAN.md' ':!docs/TESTING.md' && fail "1.5 no secrets" || pass "1.5 no secrets"
[[ -f frontend/node_modules/vite/package.json ]] && pass "1.6 frontend deps" || fail "1.6 frontend deps"
PYTHONPATH=backend python3 -c "from app.providers import build_transcription_provider; build_transcription_provider()" && pass "1.7 providers" || fail "1.7 providers"

# Phase 2/3 simulation
echo "=== Phase 2 & 3 ==="
python3 scripts/make_test_audio.py /tmp/afterword-chunk.webm >/dev/null
SESSION_ID=$(curl -sf -X POST http://127.0.0.1:8000/api/sessions | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")
curl -sf -F "audio=@/tmp/afterword-chunk.webm" "http://127.0.0.1:8000/api/sessions/$SESSION_ID/chunks" >/dev/null && pass "3.1 chunk upload" || fail "3.1 chunk upload"
[[ -f "$SESSION_DIR/$SESSION_ID/chunk_001.webm" ]] && pass "3.2 chunk on disk" || fail "3.2 chunk on disk"
curl -sf -F "audio=@/tmp/afterword-chunk.webm" "http://127.0.0.1:8000/api/sessions/$SESSION_ID/chunks" >/dev/null
STOP_RESULT=$(curl -sf -F "audio=@/tmp/afterword-chunk.webm" "http://127.0.0.1:8000/api/sessions/$SESSION_ID/stop")
echo "$STOP_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('title')" && pass "2.4 title generated" || fail "2.4 title generated"
[[ -f "$OUTPUT_DIR/q2-planning-sync.md" ]] && pass "2.5 summary desktop file" || fail "2.5 summary desktop file"
[[ -f "$OUTPUT_DIR/q2-planning-sync-transcript.md" ]] && pass "2.6 transcript separate" || fail "2.6 transcript separate"
[[ ! -d "$SESSION_DIR/$SESSION_ID" ]] && pass "2.8 session cleanup" || fail "2.8 session cleanup"

# Phase 4 orphan cleanup
echo "=== Phase 4 ==="
STALE_ID=$(python3 scripts/create_stale_session.py)
[[ -d "$SESSION_DIR/$STALE_ID" ]] || fail "4.5 stale session setup"
start_server
[[ ! -d "$SESSION_DIR/$STALE_ID" ]] && pass "4.5 orphan cleanup" || fail "4.5 orphan cleanup"

# Summarization failure fallback
echo "=== Phase 4.4 ==="
export SUMMARIZATION_PROVIDER=mock_fail
start_server
python3 scripts/make_test_audio.py /tmp/afterword-fail.webm >/dev/null
SESSION_ID=$(curl -sf -X POST http://127.0.0.1:8000/api/sessions | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")
curl -sf -F "audio=@/tmp/afterword-fail.webm" "http://127.0.0.1:8000/api/sessions/$SESSION_ID/chunks" >/dev/null
FAIL_RESULT=$(curl -sf -F "audio=@/tmp/afterword-fail.webm" "http://127.0.0.1:8000/api/sessions/$SESSION_ID/stop")
echo "$FAIL_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('error') and d.get('transcriptFile')" && pass "4.4 summary failure fallback" || fail "4.4 summary failure fallback"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
