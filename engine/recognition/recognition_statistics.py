from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time


@dataclass(slots=True)
class RecognitionStatistics:
    """Thread-safe counters for recognition runs."""

    recognitions: int = 0
    automatic_assignments: int = 0
    review_submissions: int = 0
    accepted_corrections: int = 0
    rejected_corrections: int = 0
    unknown_results: int = 0
    processed: int = 0
    recognized: int = 0
    skipped: int = 0
    failed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    candidates_ranked: int = 0
    confidence_total: float = 0.0
    confidence_samples: int = 0
    matching_time_seconds: float = 0.0
    ranking_time_seconds: float = 0.0
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
            self.recognitions += 1

    def increment_recognized(self) -> None:
        with self._lock:
            self.recognized += 1

    def increment_automatic_assignment(self) -> None:
        with self._lock:
            self.automatic_assignments += 1

    def increment_review_submission(self) -> None:
        with self._lock:
            self.review_submissions += 1

    def increment_accepted_correction(self) -> None:
        with self._lock:
            self.accepted_corrections += 1

    def increment_rejected_correction(self) -> None:
        with self._lock:
            self.rejected_corrections += 1

    def increment_unknown_result(self) -> None:
        with self._lock:
            self.unknown_results += 1

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

    def add_matching_time(self, elapsed_seconds: float) -> None:
        with self._lock:
            self.matching_time_seconds += max(0.0, elapsed_seconds)

    def add_ranking_time(self, elapsed_seconds: float) -> None:
        with self._lock:
            self.ranking_time_seconds += max(0.0, elapsed_seconds)

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

    @property
    def unknown_rate(self) -> float:
        with self._lock:
            if self.recognitions == 0:
                return 0.0
            return round(self.unknown_results / float(self.recognitions), 4)
