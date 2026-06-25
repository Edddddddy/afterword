from dataclasses import dataclass
from enum import Enum
from typing import Any


class SessionState(str, Enum):
    RECORDING = "recording"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class SummarizedMeeting:
    title: str
    markdown_body: str


@dataclass
class SessionStatus:
    session_id: str
    state: SessionState
    chunks_received: int
    transcript_length: int
    title: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "state": self.state.value,
            "chunksReceived": self.chunks_received,
            "transcriptLength": self.transcript_length,
            "title": self.title,
            "error": self.error,
        }
