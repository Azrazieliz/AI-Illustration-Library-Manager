from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time


@dataclass(slots=True)
class RecognitionStatistics:
    """Thread-safe counters for recognition runs."""

    processed: int = 0
    recognized: int = 0
    skipped: int = 0
    failed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    candidates_ranked: int = 0
    confidence_total: float = 0.0
    confidence_samples: int = 0
    elapsed_seconds: float = 0.0
    _start_time: float = 0.0
    _lock: Lock = field(default_factory=Lock, init=False)

    def start(self) -> None:
        """Mark the run start time."""
        with self._lock:
            self._start_time = time()

    def finish(self) -> None:
        """Mark the run finish time."""
        with self._lock:
            if self._start_time > 0:
                self.elapsed_seconds = time() - self._start_time

    def increment_processed(self) -> None:
        with self._lock:
            self.processed += 1

    def increment_recognized(self) -> None:
        with self._lock:
            self.recognized += 1

    def increment_skipped(self) -> None:
        with self._lock:
            self.skipped += 1

    def increment_failed(self) -> None:
        with self._lock:
            self.failed += 1

    def increment_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def increment_cache_miss(self) -> None:
        with self._lock:
            self.cache_misses += 1

    def add_candidates_ranked(self, count: int) -> None:
        with self._lock:
            self.candidates_ranked += max(0, count)

    def record_confidence(self, confidence: float | None) -> None:
        if confidence is None:
            return
        with self._lock:
            self.confidence_total += confidence
            self.confidence_samples += 1

    @property
    def average_confidence(self) -> float | None:
        with self._lock:
            if self.confidence_samples == 0:
                return None
            return round(self.confidence_total / self.confidence_samples, 4)
