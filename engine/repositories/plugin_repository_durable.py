from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from sqlalchemy import delete, select

from engine.database.models.plugin_runtime import PluginRuntimeRecord
from engine.database.session import session_scope
from engine.plugin_system.plugin_models import (
    PluginDependency,
    PluginHealth,
    PluginHealthStatus,
    PluginHookType,
    PluginManifest,
    PluginRuntime,
    PluginScheduledTask,
    PluginState,
)


class DurablePluginRepository:
    """Transactional persistence for plugin registration and user-managed state."""

    _lock = RLock()

    @classmethod
    def reset_state(cls) -> None:
        with cls._lock, session_scope() as session:
            session.execute(delete(PluginRuntimeRecord))

    def register_manifest(self, manifest: PluginManifest) -> PluginRuntime:
        with self._lock, session_scope() as session:
            row = self._get_row(session, manifest.plugin_id)
            if row is None:
                row = PluginRuntimeRecord(
                    plugin_id=manifest.plugin_id,
                    manifest_payload=self._manifest_payload(manifest),
                    state=PluginState.REGISTERED.value,
                    enabled=manifest.enabled_by_default,
                    config=dict(manifest.default_config),
                    health_payload=self._health_payload(PluginHealth()),
                    subscriptions=sorted(manifest.subscribed_events),
                    scheduled_tasks={},
                )
                session.add(row)
            else:
                existing_config = dict(row.config or {})
                row.manifest_payload = self._manifest_payload(manifest)
                row.config = {**dict(manifest.default_config), **existing_config}
                if not row.enabled:
                    row.state = PluginState.DISABLED.value
                elif row.state != PluginState.FAILED.value:
                    row.state = PluginState.REGISTERED.value
                if not row.subscriptions:
                    row.subscriptions = sorted(manifest.subscribed_events)
            session.flush()
            return self._to_runtime(row)

    def remove_plugin(self, plugin_id: str) -> bool:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def get_runtime(self, plugin_id: str) -> PluginRuntime | None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            return None if row is None else self._to_runtime(row)

    def list_runtimes(self) -> list[PluginRuntime]:
        with self._lock, session_scope() as session:
            rows = list(session.scalars(select(PluginRuntimeRecord).order_by(PluginRuntimeRecord.plugin_id)))
            return [self._to_runtime(row) for row in rows]

    def list_enabled_runtimes(self) -> list[PluginRuntime]:
        return [runtime for runtime in self.list_runtimes() if runtime.enabled]

    def recover_loaded_runtimes(self) -> None:
        """Reset process-local loaded state before a fresh engine imports plugin modules."""
        with self._lock, session_scope() as session:
            rows = list(
                session.scalars(
                    select(PluginRuntimeRecord).where(PluginRuntimeRecord.state == PluginState.LOADED.value)
                )
            )
            for row in rows:
                row.state = PluginState.REGISTERED.value

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginRuntime | None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return None
            row.enabled = bool(enabled)
            row.state = PluginState.REGISTERED.value if row.enabled else PluginState.DISABLED.value
            session.flush()
            return self._to_runtime(row)

    def set_loaded(self, plugin_id: str) -> PluginRuntime | None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return None
            row.state = PluginState.LOADED.value
            row.loaded_at = datetime.now(timezone.utc)
            row.unloaded_at = None
            session.flush()
            return self._to_runtime(row)

    def set_unloaded(self, plugin_id: str) -> PluginRuntime | None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return None
            row.state = PluginState.UNLOADED.value
            row.unloaded_at = datetime.now(timezone.utc)
            session.flush()
            return self._to_runtime(row)

    def set_failed(self, plugin_id: str, error: str) -> PluginRuntime | None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return None
            health = self._to_health(row.health_payload)
            health.status = PluginHealthStatus.UNHEALTHY
            health.last_error = str(error)
            health.last_checked_at = datetime.now(timezone.utc)
            health.consecutive_failures += 1
            health.consecutive_successes = 0
            row.state = PluginState.FAILED.value
            row.health_payload = self._health_payload(health)
            session.flush()
            return self._to_runtime(row)

    def update_config(self, plugin_id: str, config: dict[str, Any]) -> PluginRuntime | None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return None
            row.config = dict(config)
            session.flush()
            return self._to_runtime(row)

    def update_health_success(self, plugin_id: str) -> PluginHealth | None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return None
            health = self._to_health(row.health_payload)
            health.last_checked_at = datetime.now(timezone.utc)
            health.last_error = None
            health.consecutive_successes += 1
            health.consecutive_failures = 0
            health.status = PluginHealthStatus.HEALTHY
            row.health_payload = self._health_payload(health)
            return health

    def update_health_failure(self, plugin_id: str, error: str) -> PluginHealth | None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return None
            health = self._to_health(row.health_payload)
            health.last_checked_at = datetime.now(timezone.utc)
            health.last_error = str(error)
            health.consecutive_failures += 1
            health.consecutive_successes = 0
            health.status = PluginHealthStatus.DEGRADED if health.consecutive_failures < 3 else PluginHealthStatus.UNHEALTHY
            row.health_payload = self._health_payload(health)
            return health

    def subscriptions_for_event(self, event_name: str) -> list[str]:
        with self._lock, session_scope() as session:
            rows = list(session.scalars(select(PluginRuntimeRecord).order_by(PluginRuntimeRecord.plugin_id)))
            return [row.plugin_id for row in rows if event_name in set(row.subscriptions or [])]

    def set_subscriptions(self, plugin_id: str, event_names: set[str]) -> None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is not None:
                row.subscriptions = sorted({str(event_name) for event_name in event_names})

    def next_due_scheduled_tasks(self, now: datetime | None = None) -> list[tuple[str, str]]:
        reference = self._as_utc(now or datetime.now(timezone.utc))
        due: list[tuple[str, str]] = []
        with self._lock, session_scope() as session:
            rows = list(session.scalars(select(PluginRuntimeRecord).order_by(PluginRuntimeRecord.plugin_id)))
            for row in rows:
                for task_id, next_run in self._scheduled_tasks(row).items():
                    if next_run <= reference:
                        due.append((row.plugin_id, task_id))
        return due

    def schedule_task(self, plugin_id: str, task_id: str, interval_seconds: int, now: datetime | None = None) -> None:
        reference = self._as_utc(now or datetime.now(timezone.utc))
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return
            tasks = self._scheduled_tasks(row)
            tasks[str(task_id)] = reference + timedelta(seconds=max(1, interval_seconds))
            row.scheduled_tasks = {identifier: value.isoformat() for identifier, value in tasks.items()}

    def ensure_scheduled_task(self, plugin_id: str, task_id: str, interval_seconds: int, now: datetime | None = None) -> None:
        reference = self._as_utc(now or datetime.now(timezone.utc))
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is None:
                return
            tasks = self._scheduled_tasks(row)
            tasks.setdefault(str(task_id), reference + timedelta(seconds=max(1, interval_seconds)))
            row.scheduled_tasks = {identifier: value.isoformat() for identifier, value in tasks.items()}

    def clear_scheduled_tasks(self, plugin_id: str) -> None:
        with self._lock, session_scope() as session:
            row = self._get_row(session, plugin_id)
            if row is not None:
                row.scheduled_tasks = {}

    @staticmethod
    def _get_row(session, plugin_id: str) -> PluginRuntimeRecord | None:
        return session.scalar(select(PluginRuntimeRecord).where(PluginRuntimeRecord.plugin_id == str(plugin_id)))

    @classmethod
    def _to_runtime(cls, row: PluginRuntimeRecord) -> PluginRuntime:
        manifest = cls._to_manifest(dict(row.manifest_payload or {}))
        return PluginRuntime(
            manifest=manifest,
            state=cls._to_state(row.state),
            enabled=bool(row.enabled),
            loaded_at=cls._as_utc_or_none(row.loaded_at),
            unloaded_at=cls._as_utc_or_none(row.unloaded_at),
            config=dict(row.config or {}),
            health=cls._to_health(row.health_payload),
        )

    @staticmethod
    def _manifest_payload(manifest: PluginManifest) -> dict[str, Any]:
        return {
            "plugin_id": manifest.plugin_id,
            "name": manifest.name,
            "version": manifest.version,
            "entrypoint": manifest.entrypoint,
            "api_version": manifest.api_version,
            "app_version": manifest.app_version,
            "dependencies": [
                {"plugin_id": dependency.plugin_id, "version_constraint": dependency.version_constraint}
                for dependency in manifest.dependencies
            ],
            "enabled_by_default": manifest.enabled_by_default,
            "permissions": sorted(manifest.permissions),
            "subscribed_events": sorted(manifest.subscribed_events),
            "hooks": {hook_type.value: callable_name for hook_type, callable_name in manifest.hooks.items()},
            "commands": dict(manifest.commands),
            "settings_schema": dict(manifest.settings_schema),
            "default_config": dict(manifest.default_config),
            "background_tasks": list(manifest.background_tasks),
            "scheduled_tasks": [
                {
                    "task_id": task.task_id,
                    "callable_name": task.callable_name,
                    "interval_seconds": task.interval_seconds,
                }
                for task in manifest.scheduled_tasks
            ],
            "sandboxed": manifest.sandboxed,
            "plugin_directory": None if manifest.plugin_directory is None else str(manifest.plugin_directory),
        }

    @classmethod
    def _to_manifest(cls, payload: dict[str, Any]) -> PluginManifest:
        return PluginManifest(
            plugin_id=str(payload.get("plugin_id", "")),
            name=str(payload.get("name", "")),
            version=str(payload.get("version", "")),
            entrypoint=str(payload.get("entrypoint", "plugin.py")),
            api_version=str(payload.get("api_version", "1.0")),
            app_version=str(payload.get("app_version", ">=0.1.0")),
            dependencies=[
                PluginDependency(
                    plugin_id=str(item.get("plugin_id", "")),
                    version_constraint=str(item.get("version_constraint", "")),
                )
                for item in payload.get("dependencies", [])
                if isinstance(item, dict)
            ],
            enabled_by_default=bool(payload.get("enabled_by_default", True)),
            permissions={str(item) for item in payload.get("permissions", [])},
            subscribed_events={str(item) for item in payload.get("subscribed_events", [])},
            hooks={
                PluginHookType(str(hook_type)): str(callable_name)
                for hook_type, callable_name in dict(payload.get("hooks", {})).items()
            },
            commands={str(key): str(value) for key, value in dict(payload.get("commands", {})).items()},
            settings_schema=dict(payload.get("settings_schema", {})),
            default_config=dict(payload.get("default_config", {})),
            background_tasks=[str(item) for item in payload.get("background_tasks", [])],
            scheduled_tasks=[
                PluginScheduledTask(
                    task_id=str(item.get("task_id", "")),
                    callable_name=str(item.get("callable_name", "")),
                    interval_seconds=max(1, int(item.get("interval_seconds", 60))),
                )
                for item in payload.get("scheduled_tasks", [])
                if isinstance(item, dict)
            ],
            sandboxed=bool(payload.get("sandboxed", True)),
            plugin_directory=(
                None
                if payload.get("plugin_directory") in {None, ""}
                else Path(str(payload.get("plugin_directory")))
            ),
        )

    @staticmethod
    def _health_payload(health: PluginHealth) -> dict[str, Any]:
        return {
            "status": health.status.value,
            "last_error": health.last_error,
            "last_checked_at": health.last_checked_at.isoformat(),
            "consecutive_failures": health.consecutive_failures,
            "consecutive_successes": health.consecutive_successes,
        }

    @classmethod
    def _to_health(cls, payload: dict[str, Any] | None) -> PluginHealth:
        data = dict(payload or {})
        try:
            status = PluginHealthStatus(str(data.get("status", PluginHealthStatus.HEALTHY.value)))
        except ValueError:
            status = PluginHealthStatus.HEALTHY
        return PluginHealth(
            status=status,
            last_error=data.get("last_error"),
            last_checked_at=cls._as_utc_or_none(cls._parse_datetime(data.get("last_checked_at"))) or datetime.now(timezone.utc),
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            consecutive_successes=int(data.get("consecutive_successes", 0)),
        )

    @classmethod
    def _scheduled_tasks(cls, row: PluginRuntimeRecord) -> dict[str, datetime]:
        out: dict[str, datetime] = {}
        for task_id, value in dict(row.scheduled_tasks or {}).items():
            parsed = cls._parse_datetime(value)
            if parsed is not None:
                out[str(task_id)] = cls._as_utc(parsed)
        return out

    @staticmethod
    def _to_state(value: str) -> PluginState:
        try:
            return PluginState(value)
        except ValueError:
            return PluginState.REGISTERED

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @classmethod
    def _as_utc_or_none(cls, value: datetime | None) -> datetime | None:
        return None if value is None else cls._as_utc(value)