from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class HashAlgorithm(str, Enum):
    """Supported hash algorithms."""

    SHA256 = "sha256"
    PHASH = "phash"
    AHASH = "ahash"
    DHASH = "dhash"


@dataclass(slots=True)
class HashResult:
    """Result of computing all requested hashes for a single file."""

    source_path: str
    sha256: str
    phash: str | None = None
    ahash: str | None = None
    dhash: str | None = None
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HashRecord:
    """Projection of a persisted hash record returned from the repository."""

    source_path: str
    image_id: int
    sha256: str
    phash: str | None = None
    ahash: str | None = None
    dhash: str | None = None


@dataclass(slots=True)
class DuplicateCandidate:
    """Comparison-ready structure for the duplicate detection stage.

    Bundles all computed hashes for a single indexed file.  The duplicate
    detector consumes these structures to perform efficient pairwise
    comparisons without re-reading the database.
    """

    source_path: str
    image_id: int
    sha256: str
    phash: str | None = None
    ahash: str | None = None
    dhash: str | None = None
    prepared_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class HashCheckpoint:
    """Minimal crash-recovery checkpoint for an interrupted hashing run.

    ``processed_paths`` is the set of absolute resolved path strings that were
    successfully hashed before the interruption.  On restart the engine skips
    any path already present in this set.
    """

    processed_paths: set[str] = field(default_factory=set)
    completed: bool = False
