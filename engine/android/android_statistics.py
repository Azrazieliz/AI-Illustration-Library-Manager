from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from engine.android.android_models import AndroidStatistics


@dataclass(slots=True)
class _AndroidStatsState:
    bridge_calls: int = 0
    recognition_requests: int = 0
    searches: int = 0
    running_jobs: int = 0
    total_latency_ms: float = 0.0
    background_tasks: int = 0
    cache_usage_bytes: int = 0
    memory_usage_bytes: int = 0


class AndroidStatisticsTracker:
    """Thread-safe collector for Android bridge/service performance metrics."""

    def __init__(self) -> None:
        self._state = _AndroidStatsState()
        self._lock = Lock()

    def record_bridge_call(self, latency_ms: float) -> None:
        with self._lock:
            self._state.bridge_calls += 1
            self._state.total_latency_ms += max(0.0, latency_ms)

    def record_recognition_request(self) -> None:
        with self._lock:
            self._state.recognition_requests += 1

    def record_search_request(self) -> None:
        with self._lock:
            self._state.searches += 1

    def set_running_jobs(self, value: int) -> None:
        with self._lock:
            self._state.running_jobs = max(0, value)

    def set_background_tasks(self, value: int) -> None:
        with self._lock:
            self._state.background_tasks = max(0, value)

    def set_cache_usage_bytes(self, value: int) -> None:
        with self._lock:
            self._state.cache_usage_bytes = max(0, value)

    def set_memory_usage_bytes(self, value: int) -> None:
        with self._lock:
            self._state.memory_usage_bytes = max(0, value)

    def snapshot(self) -> AndroidStatistics:
        with self._lock:
            average_latency = (
                self._state.total_latency_ms / self._state.bridge_calls
                if self._state.bridge_calls
                else 0.0
            )
            return AndroidStatistics(
                bridge_calls=self._state.bridge_calls,
                recognition_requests=self._state.recognition_requests,
                searches=self._state.searches,
                running_jobs=self._state.running_jobs,
                average_latency_ms=average_latency,
                background_tasks=self._state.background_tasks,
                cache_usage_bytes=self._state.cache_usage_bytes,
                memory_usage_bytes=self._state.memory_usage_bytes,
            )
