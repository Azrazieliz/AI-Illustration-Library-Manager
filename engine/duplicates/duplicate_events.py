from __future__ import annotations

from dataclasses import dataclass

from engine.duplicates.duplicate_models import DuplicatePair


@dataclass(slots=True)
class DuplicateStarted:
    """Raised when the engine begins processing a new candidate."""

    source_path: str


@dataclass(slots=True)
class DuplicateFound:
    """Raised when a duplicate pair is confirmed."""

    pair: DuplicatePair


@dataclass(slots=True)
class DuplicateRejected:
    """Raised when a candidate comparison is evaluated and rejected."""

    source_path_a: str
    source_path_b: str
    reason: str


@dataclass(slots=True)
class DuplicateCompleted:
    """Raised when a full duplicate detection run finishes."""

    total_processed: int
    total_found: int
    total_rejected: int
