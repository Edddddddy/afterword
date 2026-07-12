import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import SessionState

logger = logging.getLogger(__name__)

TRANSCRIPT_DELIMITER = "\n\n---\n\n"
METADATA_FILE = "metadata.json"
TRANSCRIPT_FILE = "transcript.txt"
ALLOWED_CHUNK_EXTENSIONS = frozenset({"webm", "mp4", "ogg"})


class SessionError(Exception):
    pass


def normalize_chunk_extension(extension: str) -> str:
    ext = extension.lstrip(".").lower()
    if not ext:
        return "webm"
    if ext not in ALLOWED_CHUNK_EXTENSIONS:
        raise SessionError(
            "Unsupported audio extension "
            f"{ext!r}. Allowed: {', '.join(sorted(ALLOWED_CHUNK_EXTENSIONS))}"
        )
    return ext


def _chunk_path_within_session(session_dir: Path, chunk_path: Path) -> None:
    try:
        chunk_path.resolve().relative_to(session_dir.resolve())
    except ValueError as exc:
        raise SessionError("Invalid chunk path") from exc


class SessionManager:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or settings.resolved_session_dir())
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _validate_session_id(self, session_id: str) -> uuid.UUID:
        try:
            parsed = uuid.UUID(session_id, version=4)
        except ValueError as exc:
            raise SessionError("Invalid session ID") from exc
        return parsed

    def session_path(self, session_id: str) -> Path:
        parsed = self._validate_session_id(session_id)
        path = (self.base_dir / str(parsed)).resolve()
        if not str(path).startswith(str(self.base_dir.resolve())):
            raise SessionError("Invalid session path")
        return path

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        path = self.session_path(session_id)
        path.mkdir(parents=True, exist_ok=True)
        metadata = {
            "session_id": session_id,
            "state": SessionState.RECORDING.value,
            "chunks_received": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "title": None,
            "summary_file": None,
            "transcript_file": None,
            "error": None,
        }
        self._write_metadata(path, metadata)
        return session_id

    def read_metadata(self, session_id: str) -> dict:
        path = self.session_path(session_id)
        metadata_path = path / METADATA_FILE
        if not metadata_path.exists():
            raise SessionError("Session not found")
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def update_metadata(self, session_id: str, **updates: object) -> dict:
        metadata = self.read_metadata(session_id)
        metadata.update(updates)
        self._write_metadata(self.session_path(session_id), metadata)
        return metadata

    def _write_metadata(self, path: Path, metadata: dict) -> None:
        (path / METADATA_FILE).write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )

    def next_chunk_path(self, session_id: str) -> Path:
        metadata = self.read_metadata(session_id)
        chunk_number = metadata["chunks_received"] + 1
        return self.session_path(session_id) / f"chunk_{chunk_number:03d}.webm"

    def save_chunk(
        self,
        session_id: str,
        data: bytes,
        extension: str = "webm",
        chunk_path: Path | None = None,
    ) -> Path:
        if len(data) > settings.max_chunk_bytes:
            raise SessionError(
                f"Chunk exceeds maximum size of {settings.max_chunk_bytes} bytes"
            )
        safe_ext = normalize_chunk_extension(extension)
        session_dir = self.session_path(session_id)
        if chunk_path is None:
            metadata = self.read_metadata(session_id)
            chunk_number = metadata["chunks_received"] + 1
            path = session_dir / f"chunk_{chunk_number:03d}.{safe_ext}"
        else:
            path = chunk_path
        _chunk_path_within_session(session_dir, path)
        path.write_bytes(data)
        metadata = self.read_metadata(session_id)
        self.update_metadata(
            session_id,
            chunks_received=metadata["chunks_received"] + 1,
        )
        return path

    def rollback_chunk(self, session_id: str, chunk_path: Path) -> None:
        session_dir = self.session_path(session_id)
        _chunk_path_within_session(session_dir, chunk_path)
        resolved = chunk_path.resolve()
        if resolved.exists():
            resolved.unlink()
        metadata = self.read_metadata(session_id)
        if metadata["chunks_received"] > 0:
            self.update_metadata(
                session_id,
                chunks_received=metadata["chunks_received"] - 1,
            )

    def append_transcript(self, session_id: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        transcript_path = self.session_path(session_id) / TRANSCRIPT_FILE
        if transcript_path.exists() and transcript_path.stat().st_size > 0:
            existing = transcript_path.read_text(encoding="utf-8")
            content = existing + TRANSCRIPT_DELIMITER + text
        else:
            content = text
        transcript_path.write_text(content, encoding="utf-8")

    def read_transcript(self, session_id: str) -> str:
        transcript_path = self.session_path(session_id) / TRANSCRIPT_FILE
        if not transcript_path.exists():
            return ""
        return transcript_path.read_text(encoding="utf-8").strip()

    def transcript_length(self, session_id: str) -> int:
        return len(self.read_transcript(session_id))

    def sweep_orphaned_sessions(self) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - (
            settings.session_ttl_hours * 3600
        )
        removed = 0
        for entry in self.base_dir.iterdir():
            if not entry.is_dir():
                continue
            metadata_path = entry / METADATA_FILE
            if not metadata_path.exists():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                created = datetime.fromisoformat(metadata["created_at"])
                if created.timestamp() < cutoff:
                    shutil.rmtree(entry)
                    removed += 1
                    logger.info("Removed orphaned session %s", entry.name)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        return removed
