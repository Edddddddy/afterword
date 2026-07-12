from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> str | None:
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return str(candidate)
        if directory == Path.home():
            break
    return None


def _project_root() -> Path:
    for directory in [Path.cwd(), *Path.cwd().parents]:
        if (directory / "backend").is_dir() and (directory / "frontend").is_dir():
            return directory
        if directory == Path.home():
            break
    return Path.cwd()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file() or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_whisper_model: str = "whisper-1"
    openai_summary_model: str = "gpt-5.2"
    chunk_interval_seconds: int = 1800
    output_dir: Path = Field(default=Path(".afterword/output"))
    session_dir: Path = Field(default=Path(".afterword/sessions"))
    host: str = "127.0.0.1"
    port: int = 8000
    transcription_provider: str = "openai"
    summarization_provider: str = "openai"
    session_ttl_hours: int = 24
    max_chunk_bytes: int = 25 * 1024 * 1024

    def resolved_output_dir(self) -> Path:
        path = self.output_dir.expanduser()
        if not path.is_absolute():
            path = _project_root() / path
        return path.resolve()

    def resolved_session_dir(self) -> Path:
        path = self.session_dir.expanduser()
        if not path.is_absolute():
            path = _project_root() / path
        return path.resolve()


settings = Settings()
