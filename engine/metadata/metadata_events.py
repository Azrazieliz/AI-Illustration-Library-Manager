from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class MetadataStarted:
    """Raised when metadata extraction begins for a file."""

    path: Path


@dataclass(slots=True)
class MetadataExtracted:
    """Raised when metadata extraction succeeds for a file."""

    path: Path
    mime_type: str | None
    width: int | None
    height: int | None


@dataclass(slots=True)
class MetadataFailed:
    """Raised when metadata extraction fails for a file."""

    path: Path
    error: str


@dataclass(slots=True)
class MetadataCompleted:
    """Raised when a batch metadata extraction run finishes."""

    total: int
    extracted: int
    unsupported: int
    corrupted: int
    failed: int
