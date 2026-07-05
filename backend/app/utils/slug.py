import re
import unicodedata
from pathlib import Path


def slugify(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\w\s-]", "", ascii_text.lower())
    slug = re.sub(r"[-\s]+", "-", cleaned).strip("-")
    return slug or "meeting-notes"


def unique_file_path(directory: Path, slug: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{slug}{suffix}"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = directory / f"{slug}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
