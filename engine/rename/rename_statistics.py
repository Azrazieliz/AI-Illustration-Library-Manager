from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter


@dataclass(slots=True)
class RenameStatistics:
    """Thread-safe counters and timing for rename operations."""

    processed: int = 0
    previewed: int = 0
    renamed: int = 0
    skipped: int = 0
    conflicts_resolved: int = 0
    rolled_back: int = 0
    failed: int = 0
    dry_run_count: int = 0
    elapsed_seconds: float = 0.0
    _started_at: float | None = None
    _lock: Lock = field(default_factory=Lock, init=False)

    def start(self) -> None:
        with self._lock:
            self._started_at = perf_counter()

    def finish(self) -> None:
        with self._lock:
            if self._started_at is not None:
                self.elapsed_seconds = perf_counter() - self._started_at

    def increment_processed(self) -> None:
        with self._lock:
            self.processed += 1

    def increment_previewed(self) -> None:
        with self._lock:
            self.previewed += 1

    def increment_renamed(self) -> None:
        with self._lock:
            self.renamed += 1

    def increment_skipped(self) -> None:
        with self._lock:
            self.skipped += 1

    def increment_conflicts_resolved(self) -> None:
        with self._lock:
            self.conflicts_resolved += 1

    def increment_rolled_back(self) -> None:
        with self._lock:
            self.rolled_back += 1

    def increment_failed(self) -> None:
        with self._lock:
            self.failed += 1

    def increment_dry_run(self) -> None:
        with self._lock:
            self.dry_run_count += 1
