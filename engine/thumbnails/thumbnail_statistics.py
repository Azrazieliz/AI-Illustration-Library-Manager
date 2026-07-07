from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass(slots=True)
class ThumbnailStatistics:
    """Counters and timing for a thumbnail generation run."""

    processed: int = 0
    """Total images visited (includes cached and failed)."""

    generated: int = 0
    """Images for which at least one thumbnail was freshly written to disk."""

    cached: int = 0
    """Images whose thumbnails were fully served from the cache."""

    failed: int = 0
    """Images that raised an error during generation."""

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
