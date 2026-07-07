from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time


@dataclass(slots=True)
class AutomationStatistics:
    scheduled_jobs: int = 0
    queued_runs: int = 0
    failed_runs: int = 0
    skipped_runs: int = 0
    retry_attempts: int = 0
    cancelled_jobs: int = 0
    resumed_jobs: int = 0
    paused_jobs: int = 0
    manual_triggers: int = 0
    event_triggers: int = 0
    pipeline_triggers: int = 0
    maintenance_jobs_created: int = 0
    history_entries: int = 0
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

    def increment(self, field_name: str, value: int = 1) -> None:
        with self._lock:
            setattr(self, field_name, int(getattr(self, field_name)) + int(value))
