from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class PluginState(str, Enum):
    DISCOVERED = "discovered"
    REGISTERED = "registered"
    LOADED = "loaded"
    UNLOADED = "unloaded"
    DISABLED = "disabled"
    FAILED = "failed"


class PluginHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class PluginHookType(str, Enum):
    PIPELINE = "pipeline"
    SEARCH = "search"
    RECOGNITION = "recognition"
    METADATA = "metadata"
    EXPORT = "export"
    IMPORT = "import"


@dataclass(slots=True)
class PluginDependency:
    plugin_id: str
    version_constraint: str = ""


@dataclass(slots=True)
class PluginScheduledTask:
    task_id: str
    callable_name: str
    interval_seconds: int


@dataclass(slots=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    entrypoint: str = "plugin.py"
    api_version: str = "1.0"
    app_version: str = ">=0.1.0"
    dependencies: list[PluginDependency] = field(default_factory=list)
    enabled_by_default: bool = True
    permissions: set[str] = field(default_factory=set)
    subscribed_events: set[str] = field(default_factory=set)
    hooks: dict[PluginHookType, str] = field(default_factory=dict)
    commands: dict[str, str] = field(default_factory=dict)
    settings_schema: dict[str, Any] = field(default_factory=dict)
    default_config: dict[str, Any] = field(default_factory=dict)
    background_tasks: list[str] = field(default_factory=list)
    scheduled_tasks: list[PluginScheduledTask] = field(default_factory=list)
    sandboxed: bool = True
    plugin_directory: Path | None = None


@dataclass(slots=True)
class PluginHealth:
    status: PluginHealthStatus = PluginHealthStatus.HEALTHY
    last_error: str | None = None
    last_checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consecutive_failures: int = 0
    consecutive_successes: int = 0


@dataclass(slots=True)
class PluginRuntime:
    manifest: PluginManifest
    state: PluginState = PluginState.DISCOVERED
    enabled: bool = True
    loaded_at: datetime | None = None
    unloaded_at: datetime | None = None
    config: dict[str, Any] = field(default_factory=dict)
    health: PluginHealth = field(default_factory=PluginHealth)


@dataclass(slots=True)
class PluginCommandResult:
    plugin_id: str
    command: str
    success: bool
    payload: Any = None
    error: str | None = None


@dataclass(slots=True)
class PluginHookResult:
    plugin_id: str
    hook_type: PluginHookType
    success: bool
    payload: Any = None
    error: str | None = None


@dataclass(slots=True)
class PluginEventResult:
    plugin_id: str
    event_name: str
    success: bool
    error: str | None = None


@dataclass(slots=True)
class PluginDiscoveryResult:
    discovered: list[PluginManifest] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class PluginOperationResult:
    action: str
    success: bool
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PluginCheckpoint:
    processed_job_ids: set[str] = field(default_factory=set)
    cancelled_job_ids: set[str] = field(default_factory=set)

    def add_processed(self, job_id: str) -> None:
        self.processed_job_ids.add(str(job_id))

    def is_processed(self, job_id: str) -> bool:
        return str(job_id) in self.processed_job_ids

    def cancel(self, job_id: str) -> None:
        self.cancelled_job_ids.add(str(job_id))

    def resume(self, job_id: str) -> None:
        self.cancelled_job_ids.discard(str(job_id))

    def is_cancelled(self, job_id: str) -> bool:
        return str(job_id) in self.cancelled_job_ids
