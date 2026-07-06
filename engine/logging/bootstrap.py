from __future__ import annotations

from pathlib import Path

from engine.config import settings


def ensure_log_directory(log_directory: Path | str | None = None) -> Path:
    """Create the log directory if it does not already exist."""
    directory = Path(log_directory or settings.log_directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
