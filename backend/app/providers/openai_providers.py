import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.models import SummarizedMeeting
from app.providers.base import SummarizationProvider, TranscriptionProvider

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = """You summarize meeting transcripts into concise markdown notes.
Return JSON with exactly two keys:
- "title": a short descriptive meeting title (3-8 words) inferred from the discussion
- "markdown_body": markdown with these sections only (no top-level H1):
  ## Summary
  ## Key decisions
  ## Action items
  ## Discussion highlights

Use bullet lists where appropriate. Action items use "- [ ]" syntax."""


class OpenAITranscriptionProvider:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_whisper_model

    async def transcribe(self, audio_path: Path) -> str:
        with audio_path.open("rb") as audio_file:
            result = await self._client.audio.transcriptions.create(
                model=self._model,
                file=audio_file,
            )
        return (result.text or "").strip()


class OpenAISummarizationProvider:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_summary_model

    async def summarize(self, transcript: str) -> SummarizedMeeting:
        response = await self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n\n{transcript}"},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        title = str(data.get("title", "")).strip() or "Meeting Notes"
        body = str(data.get("markdown_body", "")).strip()
        if not body:
            body = "## Summary\n\n(No summary generated.)"
        return SummarizedMeeting(title=title, markdown_body=body)


class MockTranscriptionProvider:
    async def transcribe(self, audio_path: Path) -> str:
        size = audio_path.stat().st_size if audio_path.exists() else 0
        if size < 100:
            return ""
        return "This is a mock transcription for testing the Afterword pipeline."


class MockSummarizationProvider:
    async def summarize(self, transcript: str) -> SummarizedMeeting:
        if not transcript.strip():
            raise ValueError("Transcript is empty")
        return SummarizedMeeting(
            title="Q2 Planning Sync",
            markdown_body=(
                "## Summary\n\nMock summary for testing.\n\n"
                "## Key decisions\n\n- Proceed with v1 on macOS\n\n"
                "## Action items\n\n- [ ] Review gate reports\n\n"
                "## Discussion highlights\n\n- Pipeline validation"
            ),
        )


class FailingSummarizationProvider:
    async def summarize(self, transcript: str) -> SummarizedMeeting:
        raise RuntimeError("Simulated summarization failure")


def build_transcription_provider() -> TranscriptionProvider:
    if settings.transcription_provider == "mock":
        logger.info("Using mock transcription provider")
        return MockTranscriptionProvider()
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required when TRANSCRIPTION_PROVIDER=openai"
        )
    return OpenAITranscriptionProvider()


def build_summarization_provider() -> SummarizationProvider:
    if settings.summarization_provider == "mock":
        logger.info("Using mock summarization provider")
        return MockSummarizationProvider()
    if settings.summarization_provider == "mock_fail":
        logger.info("Using failing mock summarization provider")
        return FailingSummarizationProvider()
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required when SUMMARIZATION_PROVIDER=openai"
        )
    return OpenAISummarizationProvider()
