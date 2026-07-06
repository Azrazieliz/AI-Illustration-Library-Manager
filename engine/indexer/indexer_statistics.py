from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass(slots=True)
class IndexerStatistics:
    """Statistics for incremental indexing progress."""

    new: int = 0
    modified: int = 0
    unchanged: int = 0
    deleted: int = 0
    processed: int = 0
    failed: int = 0
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
