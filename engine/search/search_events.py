from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SearchStarted:
    """Raised when semantic indexing starts for a path."""

    path: Path


@dataclass(slots=True)
class SearchIndexed:
    """Raised when semantic indexing succeeds for a path."""

    path: Path
    image_id: int
    dimensions: int


@dataclass(slots=True)
class SearchSkipped:
    """Raised when semantic indexing is skipped for a path."""

    path: Path
    reason: str


@dataclass(slots=True)
class SearchFailed:
    """Raised when semantic indexing fails for a path."""

    path: Path
    error: str


@dataclass(slots=True)
class SearchCompleted:
    """Raised when a semantic indexing batch run finishes."""

    total: int
    indexed: int
    skipped: int
    failed: int
