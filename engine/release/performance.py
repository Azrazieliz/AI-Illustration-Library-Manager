from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter


@dataclass(slots=True)
class PerformanceSnapshot:
    label: str
    elapsed_seconds: float


class PerformanceTracker:
    def __init__(self) -> None:
        self._starts: dict[str, float] = {}

    def start(self, label: str) -> None:
        self._starts[label] = perf_counter()

    def stop(self, label: str) -> PerformanceSnapshot:
        started = self._starts.pop(label, perf_counter())
        return PerformanceSnapshot(label=label, elapsed_seconds=perf_counter() - started)
