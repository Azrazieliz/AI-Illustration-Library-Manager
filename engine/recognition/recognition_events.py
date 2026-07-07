from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RecognitionStarted:
    """Raised when recognition starts for a file."""

    path: Path


@dataclass(slots=True)
class RecognitionCompletedForPath:
    """Raised when recognition succeeds for a file."""

    path: Path
    image_id: int
    series: str | None
    character_count: int


@dataclass(slots=True)
class RecognitionSkipped:
    """Raised when recognition is skipped for a file."""

    path: Path
    reason: str


@dataclass(slots=True)
class RecognitionFailed:
    """Raised when recognition fails for a file."""

    path: Path
    error: str


@dataclass(slots=True)
class RecognitionCompleted:
    """Raised when a recognition batch finishes."""

    total: int
    recognized: int
    skipped: int
    failed: int
