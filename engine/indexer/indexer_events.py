from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class IndexStarted:
    """Raised when incremental indexing begins."""

    root: Path


@dataclass(slots=True)
class FileIndexed:
    """Raised when a discovered file is indexed as new or modified."""

    path: Path
    decision: str


@dataclass(slots=True)
class FileModified:
    """Raised when an existing file is detected as modified."""

    path: Path


@dataclass(slots=True)
class FileDeleted:
    """Raised when a previously indexed file is no longer present."""

    path: Path


@dataclass(slots=True)
class IndexCompleted:
    """Raised when indexing finishes."""

    root: Path
