from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass(slots=True)
class HashStatistics:
    """Counters and timing for a hashing run."""

    processed: int = 0
    """Total files visited (includes skipped and failed)."""

    hashed: int = 0
    """Files for which all hashes were freshly computed and persisted."""

    skipped: int = 0
    """Files skipped because they were already hashed with the same content."""

    failed: int = 0
    """Files that raised an error during hashing."""

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
