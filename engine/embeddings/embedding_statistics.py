from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class EmbeddingStatistics:
    """Tracks metrics for embedding generation runs."""

    processed: int = 0
    embedded: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0
    _start_time: float | None = None

    def start(self) -> None:
        """Start timing the operation."""
        self._start_time = time.time()

    def finish(self) -> None:
        """Finish timing and calculate elapsed seconds."""
        if self._start_time is not None:
            self.elapsed_seconds = time.time() - self._start_time
