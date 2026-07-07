from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time


@dataclass(slots=True)
class AdvancedSearchStatistics:
    searches: int = 0
    batch_searches: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    documents_scanned: int = 0
    cancelled_jobs: int = 0
    resumed_jobs: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0
    _start_time: float = 0.0
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def start(self) -> None:
        with self._lock:
            self._start_time = time()

    def finish(self) -> None:
        with self._lock:
            if self._start_time > 0:
                self.elapsed_seconds = time() - self._start_time

    def increment_searches(self) -> None:
        with self._lock:
            self.searches += 1

    def increment_batch_searches(self) -> None:
        with self._lock:
            self.batch_searches += 1

    def increment_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def increment_cache_miss(self) -> None:
        with self._lock:
            self.cache_misses += 1

    def add_documents_scanned(self, count: int) -> None:
        with self._lock:
            self.documents_scanned += max(0, int(count))

    def increment_cancelled(self) -> None:
        with self._lock:
            self.cancelled_jobs += 1

    def increment_resumed(self) -> None:
        with self._lock:
            self.resumed_jobs += 1

    def increment_failed(self) -> None:
        with self._lock:
            self.failed += 1
