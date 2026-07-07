from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter


@dataclass(slots=True)
class BulkStatistics:
    """Thread-safe counters and timing for bulk operations."""

    batches_created: int = 0
    batches_completed: int = 0
    batches_cancelled: int = 0
    batches_rolled_back: int = 0
    batches_resumed: int = 0
    total_items: int = 0
    processed_items: int = 0
    succeeded_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    duplicate_requests: int = 0
    dry_run_batches: int = 0
    partial_failures: int = 0
    cancelled_items: int = 0
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

    def increment_batches_created(self) -> None:
        with self._lock:
            self.batches_created += 1

    def increment_batches_completed(self) -> None:
        with self._lock:
            self.batches_completed += 1

    def increment_batches_cancelled(self) -> None:
        with self._lock:
            self.batches_cancelled += 1

    def increment_batches_rolled_back(self) -> None:
        with self._lock:
            self.batches_rolled_back += 1

    def increment_batches_resumed(self) -> None:
        with self._lock:
            self.batches_resumed += 1

    def increment_total_items(self, count: int) -> None:
        with self._lock:
            self.total_items += max(0, count)

    def increment_processed_items(self) -> None:
        with self._lock:
            self.processed_items += 1

    def increment_succeeded_items(self) -> None:
        with self._lock:
            self.succeeded_items += 1

    def increment_failed_items(self) -> None:
        with self._lock:
            self.failed_items += 1

    def increment_skipped_items(self) -> None:
        with self._lock:
            self.skipped_items += 1

    def increment_duplicate_requests(self) -> None:
        with self._lock:
            self.duplicate_requests += 1

    def increment_dry_run_batches(self) -> None:
        with self._lock:
            self.dry_run_batches += 1

    def increment_partial_failures(self) -> None:
        with self._lock:
            self.partial_failures += 1

    def increment_cancelled_items(self) -> None:
        with self._lock:
            self.cancelled_items += 1

    @property
    def progress_percentage(self) -> float:
        with self._lock:
            if self.total_items == 0:
                return 100.0
            return round((self.processed_items / self.total_items) * 100.0, 2)

    @property
    def success_rate(self) -> float:
        with self._lock:
            if self.processed_items == 0:
                return 0.0
            return round((self.succeeded_items / self.processed_items) * 100.0, 2)
