from pathlib import Path
from typing import Protocol

from app.models import SummarizedMeeting


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio_path: Path) -> str: ...


class SummarizationProvider(Protocol):
    async def summarize(self, transcript: str) -> SummarizedMeeting: ...
