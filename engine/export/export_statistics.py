from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time


@dataclass(slots=True)
class ExportStatistics:
    processed: int = 0
    exported: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0
    _start_time: float = 0.0
    _lock: Lock = field(default_factory=Lock, init=False)

    def start(self) -> None:
        with self._lock:
            self._start_time = time()

    def finish(self) -> None:
        with self._lock:
            if self._start_time > 0:
                self.elapsed_seconds = time() - self._start_time

    def increment_processed(self) -> None:
        with self._lock:
            self.processed += 1

    def increment_exported(self) -> None:
        with self._lock:
            self.exported += 1

    def increment_skipped(self) -> None:
        with self._lock:
            self.skipped += 1

    def increment_failed(self) -> None:
        with self._lock:
            self.failed += 1
