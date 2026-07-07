from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass(slots=True)
class DuplicateStatistics:
    """Counters and timing for a duplicate detection run."""

    processed: int = 0
    """Total candidates processed."""

    comparisons: int = 0
    """Total pairwise comparisons performed."""

    duplicates_found: int = 0
    """Total duplicate pairs confirmed."""

    exact_duplicates: int = 0
    """Pairs matched by identical SHA-256."""

    perceptual_duplicates: int = 0
    """Pairs matched by perceptual hash similarity."""

    false_matches_rejected: int = 0
    """Comparisons evaluated but rejected below the minimum threshold."""

    failed: int = 0
    """Candidates that raised an error during processing."""

    elapsed_seconds: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        self.started_at = perf_counter()

    def complete(self) -> None:
        if self.started_at is not None:
            self.completed_at = perf_counter()
            self.elapsed_seconds = self.completed_at - self.started_at
