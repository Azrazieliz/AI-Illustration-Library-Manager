from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time


@dataclass(slots=True)
class PluginStatistics:
    discovered: int = 0
    registered: int = 0
    loaded: int = 0
    unloaded: int = 0
    enabled: int = 0
    disabled: int = 0
    failed: int = 0
    hooks_executed: int = 0
    commands_executed: int = 0
    events_dispatched: int = 0
    background_tasks_run: int = 0
    scheduled_tasks_run: int = 0
    health_checks: int = 0
    cancellations: int = 0
    resumptions: int = 0
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
