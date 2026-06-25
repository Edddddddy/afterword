#!/usr/bin/env python3
"""Create a session directory older than 24h for orphan cleanup tests."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

session_dir = Path.home() / ".afterword" / "sessions-test"
session_dir.mkdir(parents=True, exist_ok=True)
session_id = str(uuid.uuid4())
path = session_dir / session_id
path.mkdir()
old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
metadata = {
    "session_id": session_id,
    "state": "recording",
    "chunks_received": 0,
    "created_at": old_time,
    "title": None,
    "summary_file": None,
    "transcript_file": None,
    "error": None,
}
(path / "metadata.json").write_text(json.dumps(metadata, indent=2))
print(session_id)
