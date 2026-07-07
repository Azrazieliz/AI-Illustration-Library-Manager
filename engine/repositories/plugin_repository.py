from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from engine.plugin_system.plugin_models import (
    PluginHealth,
    PluginHealthStatus,
    PluginManifest,
    PluginRuntime,
    PluginState,
)


class PluginRepository:
    """Thread-safe runtime/plugin state store for the plugin subsystem."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._plugins: dict[str, PluginRuntime] = {}
        self._event_subscriptions: dict[str, set[str]] = {}
        self._task_registry: dict[str, dict[str, datetime]] = {}

    def register_manifest(self, manifest: PluginManifest) -> PluginRuntime:
        with self._lock:
            runtime = PluginRuntime(
                manifest=manifest,
                state=PluginState.REGISTERED,
                enabled=manifest.enabled_by_default,
                config=dict(manifest.default_config),
            )
            self._plugins[manifest.plugin_id] = runtime
            self._event_subscriptions[manifest.plugin_id] = set(manifest.subscribed_events)
            self._task_registry.setdefault(manifest.plugin_id, {})
            return deepcopy(runtime)

    def remove_plugin(self, plugin_id: str) -> bool:
        with self._lock:
            existed = plugin_id in self._plugins
            self._plugins.pop(plugin_id, None)
            self._event_subscriptions.pop(plugin_id, None)
            self._task_registry.pop(plugin_id, None)
            return existed

    def get_runtime(self, plugin_id: str) -> PluginRuntime | None:
        with self._lock:
            runtime = self._plugins.get(plugin_id)
            return deepcopy(runtime) if runtime is not None else None

    def list_runtimes(self) -> list[PluginRuntime]:
        with self._lock:
            items = [deepcopy(item) for item in self._plugins.values()]
        items.sort(key=lambda item: item.manifest.plugin_id)
        return items

    def list_enabled_runtimes(self) -> list[PluginRuntime]:
        items = [item for item in self.list_runtimes() if item.enabled]
        items.sort(key=lambda item: item.manifest.plugin_id)
        return items

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginRuntime | None:
        with self._lock:
            runtime = self._plugins.get(plugin_id)
            if runtime is None:
                return None
            runtime.enabled = enabled
            runtime.state = PluginState.REGISTERED if enabled else PluginState.DISABLED
            return deepcopy(runtime)

    def set_loaded(self, plugin_id: str) -> PluginRuntime | None:
        with self._lock:
            runtime = self._plugins.get(plugin_id)
            if runtime is None:
                return None
            runtime.state = PluginState.LOADED
            runtime.loaded_at = datetime.now(timezone.utc)
            runtime.unloaded_at = None
            return deepcopy(runtime)

    def set_unloaded(self, plugin_id: str) -> PluginRuntime | None:
        with self._lock:
            runtime = self._plugins.get(plugin_id)
            if runtime is None:
                return None
            runtime.state = PluginState.UNLOADED
            runtime.unloaded_at = datetime.now(timezone.utc)
            return deepcopy(runtime)

    def set_failed(self, plugin_id: str, error: str) -> PluginRuntime | None:
        with self._lock:
            runtime = self._plugins.get(plugin_id)
            if runtime is None:
                return None
            runtime.state = PluginState.FAILED
            runtime.health.status = PluginHealthStatus.UNHEALTHY
            runtime.health.last_error = str(error)
            runtime.health.last_checked_at = datetime.now(timezone.utc)
            runtime.health.consecutive_failures += 1
            runtime.health.consecutive_successes = 0
            return deepcopy(runtime)

    def update_config(self, plugin_id: str, config: dict[str, Any]) -> PluginRuntime | None:
        with self._lock:
            runtime = self._plugins.get(plugin_id)
            if runtime is None:
                return None
            runtime.config = dict(config)
            return deepcopy(runtime)

    def update_health_success(self, plugin_id: str) -> PluginHealth | None:
        with self._lock:
            runtime = self._plugins.get(plugin_id)
            if runtime is None:
                return None
            health = runtime.health
            health.last_checked_at = datetime.now(timezone.utc)
            health.last_error = None
            health.consecutive_successes += 1
            health.consecutive_failures = 0
            health.status = PluginHealthStatus.HEALTHY
            return deepcopy(health)

    def update_health_failure(self, plugin_id: str, error: str) -> PluginHealth | None:
        with self._lock:
            runtime = self._plugins.get(plugin_id)
            if runtime is None:
                return None
            health = runtime.health
            health.last_checked_at = datetime.now(timezone.utc)
            health.last_error = str(error)
            health.consecutive_failures += 1
            health.consecutive_successes = 0
            health.status = PluginHealthStatus.DEGRADED if health.consecutive_failures < 3 else PluginHealthStatus.UNHEALTHY
            return deepcopy(health)

    def subscriptions_for_event(self, event_name: str) -> list[str]:
        with self._lock:
            out = [plugin_id for plugin_id, events in self._event_subscriptions.items() if event_name in events]
        out.sort()
        return out

    def set_subscriptions(self, plugin_id: str, event_names: set[str]) -> None:
        with self._lock:
            self._event_subscriptions[plugin_id] = set(event_names)

    def next_due_scheduled_tasks(self, now: datetime | None = None) -> list[tuple[str, str]]:
        reference = now or datetime.now(timezone.utc)
        due: list[tuple[str, str]] = []
        with self._lock:
            for plugin_id, task_map in self._task_registry.items():
                for task_id, next_run in task_map.items():
                    if next_run <= reference:
                        due.append((plugin_id, task_id))
        due.sort()
        return due

    def schedule_task(self, plugin_id: str, task_id: str, interval_seconds: int, now: datetime | None = None) -> None:
        reference = now or datetime.now(timezone.utc)
        with self._lock:
            self._task_registry.setdefault(plugin_id, {})[task_id] = reference + timedelta(seconds=max(1, interval_seconds))

    def clear_scheduled_tasks(self, plugin_id: str) -> None:
        with self._lock:
            self._task_registry[plugin_id] = {}
