from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter


@dataclass(slots=True)
class ReviewStatistics:
    """Thread-safe counters and timing for review queue operations."""

    total: int = 0
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    skipped_count: int = 0
    failed: int = 0
    batches_created: int = 0
    batches_rolled_back: int = 0
    duplicate_reviews_prevented: int = 0
    confidence_total: float = 0.0
    confidence_samples: int = 0
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

    def record_confidence(self, confidence: float | None) -> None:
        if confidence is None:
            return
        with self._lock:
            self.confidence_total += confidence
            self.confidence_samples += 1

    def increment_total(self) -> None:
        with self._lock:
            self.total += 1

    def increment_pending(self) -> None:
        with self._lock:
            self.pending_count += 1

    def decrement_pending(self) -> None:
        with self._lock:
            self.pending_count = max(0, self.pending_count - 1)

    def increment_approved(self) -> None:
        with self._lock:
            self.approved_count += 1

    def decrement_approved(self) -> None:
        with self._lock:
            self.approved_count = max(0, self.approved_count - 1)

    def increment_rejected(self) -> None:
        with self._lock:
            self.rejected_count += 1

    def decrement_rejected(self) -> None:
        with self._lock:
            self.rejected_count = max(0, self.rejected_count - 1)

    def increment_skipped(self) -> None:
        with self._lock:
            self.skipped_count += 1

    def decrement_skipped(self) -> None:
        with self._lock:
            self.skipped_count = max(0, self.skipped_count - 1)

    def increment_failed(self) -> None:
        with self._lock:
            self.failed += 1

    def increment_batches_created(self) -> None:
        with self._lock:
            self.batches_created += 1

    def increment_batches_rolled_back(self) -> None:
        with self._lock:
            self.batches_rolled_back += 1

    def increment_duplicate_reviews_prevented(self) -> None:
        with self._lock:
            self.duplicate_reviews_prevented += 1

    @property
    def average_confidence(self) -> float | None:
        with self._lock:
            if self.confidence_samples == 0:
                return None
            return round(self.confidence_total / self.confidence_samples, 4)

    @property
    def completion_percentage(self) -> float:
        with self._lock:
            if self.total == 0:
                return 0.0
            completed = self.approved_count + self.rejected_count + self.skipped_count
            return round((completed / self.total) * 100.0, 2)
