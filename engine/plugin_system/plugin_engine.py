from __future__ import annotations

import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from engine.events.event_dispatcher import EventDispatcher
from engine.logging import get_logger
from engine.plugin_system.plugin_builder import PluginBuilder
from engine.plugin_system.plugin_exceptions import (
    PluginCompatibilityError,
    PluginDependencyError,
    PluginLoadError,
    PluginPermissionError,
)
from engine.plugin_system.plugin_models import (
    PluginCommandResult,
    PluginDiscoveryResult,
    PluginEventResult,
    PluginHookResult,
    PluginHookType,
    PluginManifest,
    PluginOperationResult,
    PluginRuntime,
)
from engine.plugin_system.plugin_statistics import PluginStatistics
from engine.repositories.plugin_repository import PluginRepository


class PluginEngine:
    """Orchestrates plugin discovery, lifecycle, hooks, and safe execution."""

    _HOOK_PERMISSION = {
        PluginHookType.PIPELINE: "hooks:pipeline",
        PluginHookType.SEARCH: "hooks:search",
        PluginHookType.RECOGNITION: "hooks:recognition",
        PluginHookType.METADATA: "hooks:metadata",
        PluginHookType.EXPORT: "hooks:export",
        PluginHookType.IMPORT: "hooks:import",
    }

    def __init__(
        self,
        *,
        repository: PluginRepository | None = None,
        builder: PluginBuilder | None = None,
        dispatcher: EventDispatcher | None = None,
        callback: Callable[[object], None] | None = None,
        app_version: str = "0.1.0",
    ) -> None:
        self.repository = repository or PluginRepository()
        self.builder = builder or PluginBuilder()
        self.dispatcher = dispatcher or EventDispatcher()
        self.callback = callback
        self.app_version = app_version
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = PluginStatistics()

        self._loaded_modules: dict[str, ModuleType] = {}
        self._load_order: list[str] = []

    # ------------------------------------------------------------------
    # Discovery and registration
    # ------------------------------------------------------------------
    def discover(self, plugin_root: Path | str) -> PluginDiscoveryResult:
        root = Path(plugin_root)
        result = PluginDiscoveryResult()
        if not root.exists() or not root.is_dir():
            return result

        for entry in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "plugin.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = self.builder.parse_manifest_file(manifest_path)
                self.builder.check_version_compatibility(manifest, self.app_version)
                result.discovered.append(manifest)
            except Exception as exc:
                result.failed[str(entry)] = str(exc)

        result.discovered.sort(key=lambda item: item.plugin_id)
        self.statistics.increment("discovered", len(result.discovered))
        if result.failed:
            self.statistics.increment("failed", len(result.failed))
        return result

    def register(self, manifests: list[PluginManifest]) -> list[PluginRuntime]:
        order = self.builder.resolve_load_order(manifests)
        runtimes: list[PluginRuntime] = []
        for manifest in order:
            runtime = self.repository.register_manifest(manifest)
            runtimes.append(runtime)
        self._load_order = [item.manifest.plugin_id for item in runtimes]
        self.statistics.increment("registered", len(runtimes))
        self.statistics.increment("enabled", len([item for item in runtimes if item.enabled]))
        return runtimes

    # ------------------------------------------------------------------
    # Load/unload lifecycle
    # ------------------------------------------------------------------
    def load_all(self) -> list[PluginOperationResult]:
        results: list[PluginOperationResult] = []
        runtimes = {item.manifest.plugin_id: item for item in self.repository.list_runtimes()}
        manifests = [runtimes[plugin_id].manifest for plugin_id in self._load_order if plugin_id in runtimes]

        try:
            order = self.builder.resolve_load_order(manifests)
        except PluginDependencyError as exc:
            self.statistics.increment("failed")
            return [PluginOperationResult(action="load_all", success=False, message=str(exc))]

        for manifest in order:
            runtime = self.repository.get_runtime(manifest.plugin_id)
            if runtime is None or not runtime.enabled:
                continue
            results.append(self.load_plugin(manifest.plugin_id))

        return results

    def load_plugin(self, plugin_id: str) -> PluginOperationResult:
        runtime = self.repository.get_runtime(plugin_id)
        if runtime is None:
            return PluginOperationResult(action="load", success=False, message=f"Plugin not found: {plugin_id}")
        if not runtime.enabled:
            return PluginOperationResult(action="load", success=False, message=f"Plugin disabled: {plugin_id}")

        try:
            module = self._import_plugin_module(runtime.manifest)
            self._loaded_modules[plugin_id] = module
            self.repository.set_loaded(plugin_id)
            self._register_plugin_settings(runtime)
            self._schedule_plugin_tasks(runtime)
            self.statistics.increment("loaded")
            return PluginOperationResult(action="load", success=True, payload={"plugin_id": plugin_id})
        except Exception as exc:
            self.repository.set_failed(plugin_id, str(exc))
            self.statistics.increment("failed")
            return PluginOperationResult(action="load", success=False, message=str(exc), payload={"plugin_id": plugin_id})

    def unload_plugin(self, plugin_id: str) -> PluginOperationResult:
        runtime = self.repository.get_runtime(plugin_id)
        if runtime is None:
            return PluginOperationResult(action="unload", success=False, message=f"Plugin not found: {plugin_id}")

        try:
            module = self._loaded_modules.pop(plugin_id, None)
            if module is not None:
                if hasattr(module, "shutdown") and callable(getattr(module, "shutdown")):
                    self._safe_call(module.shutdown, payload=None, config=runtime.config)
                module_name = module.__name__
                if module_name in sys.modules:
                    del sys.modules[module_name]
            self.repository.clear_scheduled_tasks(plugin_id)
            self.repository.set_unloaded(plugin_id)
            self.statistics.increment("unloaded")
            return PluginOperationResult(action="unload", success=True, payload={"plugin_id": plugin_id})
        except Exception as exc:
            self.repository.set_failed(plugin_id, str(exc))
            self.statistics.increment("failed")
            return PluginOperationResult(action="unload", success=False, message=str(exc), payload={"plugin_id": plugin_id})

    def hot_reload(self, plugin_id: str) -> PluginOperationResult:
        unload_result = self.unload_plugin(plugin_id)
        load_result = self.load_plugin(plugin_id)
        success = unload_result.success and load_result.success
        message = "hot reload complete" if success else f"hot reload failed: {unload_result.message} | {load_result.message}"
        return PluginOperationResult(action="hot_reload", success=success, message=message, payload={"plugin_id": plugin_id})

    def enable_plugin(self, plugin_id: str) -> PluginOperationResult:
        runtime = self.repository.set_enabled(plugin_id, True)
        if runtime is None:
            return PluginOperationResult(action="enable", success=False, message=f"Plugin not found: {plugin_id}")
        self.statistics.increment("enabled")
        return PluginOperationResult(action="enable", success=True, payload={"plugin_id": plugin_id})

    def disable_plugin(self, plugin_id: str) -> PluginOperationResult:
        self.unload_plugin(plugin_id)
        runtime = self.repository.set_enabled(plugin_id, False)
        if runtime is None:
            return PluginOperationResult(action="disable", success=False, message=f"Plugin not found: {plugin_id}")
        self.statistics.increment("disabled")
        return PluginOperationResult(action="disable", success=True, payload={"plugin_id": plugin_id})

    # ------------------------------------------------------------------
    # Execution surfaces
    # ------------------------------------------------------------------
    def dispatch_event(self, event_name: str, payload: dict[str, Any] | None = None) -> list[PluginEventResult]:
        results: list[PluginEventResult] = []
        for plugin_id in self.repository.subscriptions_for_event(event_name):
            runtime = self.repository.get_runtime(plugin_id)
            module = self._loaded_modules.get(plugin_id)
            if runtime is None or module is None or not runtime.enabled:
                continue
            if "events:subscribe" not in runtime.manifest.permissions:
                results.append(PluginEventResult(plugin_id=plugin_id, event_name=event_name, success=False, error="permission denied"))
                continue

            handler = getattr(module, "on_event", None)
            if not callable(handler):
                continue

            try:
                self._safe_call(handler, payload=payload or {}, config=runtime.config, event_name=event_name)
                self.repository.update_health_success(plugin_id)
                self.statistics.increment("events_dispatched")
                results.append(PluginEventResult(plugin_id=plugin_id, event_name=event_name, success=True))
            except Exception as exc:
                self.repository.update_health_failure(plugin_id, str(exc))
                self.statistics.increment("failed")
                results.append(PluginEventResult(plugin_id=plugin_id, event_name=event_name, success=False, error=str(exc)))
        return results

    def run_hook(self, hook_type: PluginHookType, payload: dict[str, Any] | None = None) -> list[PluginHookResult]:
        results: list[PluginHookResult] = []
        permission = self._HOOK_PERMISSION[hook_type]

        for plugin_id in list(self._load_order):
            runtime = self.repository.get_runtime(plugin_id)
            module = self._loaded_modules.get(plugin_id)
            if runtime is None or module is None or not runtime.enabled:
                continue

            callable_name = runtime.manifest.hooks.get(hook_type)
            if not callable_name:
                continue

            if permission not in runtime.manifest.permissions:
                results.append(PluginHookResult(plugin_id=plugin_id, hook_type=hook_type, success=False, error="permission denied"))
                continue

            func = getattr(module, callable_name, None)
            if not callable(func):
                results.append(PluginHookResult(plugin_id=plugin_id, hook_type=hook_type, success=False, error="hook missing"))
                continue

            try:
                output = self._safe_call(func, payload=payload or {}, config=runtime.config)
                self.repository.update_health_success(plugin_id)
                self.statistics.increment("hooks_executed")
                results.append(PluginHookResult(plugin_id=plugin_id, hook_type=hook_type, success=True, payload=output))
            except Exception as exc:
                self.repository.update_health_failure(plugin_id, str(exc))
                self.statistics.increment("failed")
                results.append(PluginHookResult(plugin_id=plugin_id, hook_type=hook_type, success=False, error=str(exc)))

        return results

    def execute_command(self, plugin_id: str, command: str, payload: dict[str, Any] | None = None) -> PluginCommandResult:
        runtime = self.repository.get_runtime(plugin_id)
        module = self._loaded_modules.get(plugin_id)
        if runtime is None or module is None:
            return PluginCommandResult(plugin_id=plugin_id, command=command, success=False, error="plugin not loaded")
        if "commands:execute" not in runtime.manifest.permissions:
            return PluginCommandResult(plugin_id=plugin_id, command=command, success=False, error="permission denied")

        callable_name = runtime.manifest.commands.get(command)
        if not callable_name:
            return PluginCommandResult(plugin_id=plugin_id, command=command, success=False, error="command not found")

        func = getattr(module, callable_name, None)
        if not callable(func):
            return PluginCommandResult(plugin_id=plugin_id, command=command, success=False, error="command handler missing")

        try:
            output = self._safe_call(func, payload=payload or {}, config=runtime.config)
            self.repository.update_health_success(plugin_id)
            self.statistics.increment("commands_executed")
            return PluginCommandResult(plugin_id=plugin_id, command=command, success=True, payload=output)
        except Exception as exc:
            self.repository.update_health_failure(plugin_id, str(exc))
            self.statistics.increment("failed")
            return PluginCommandResult(plugin_id=plugin_id, command=command, success=False, error=str(exc))

    def run_background_tasks(self, plugin_id: str | None = None) -> list[PluginOperationResult]:
        targets = [plugin_id] if plugin_id else list(self._load_order)
        results: list[PluginOperationResult] = []

        for current_plugin_id in targets:
            runtime = self.repository.get_runtime(current_plugin_id)
            module = self._loaded_modules.get(current_plugin_id)
            if runtime is None or module is None or not runtime.enabled:
                continue
            if "tasks:background" not in runtime.manifest.permissions:
                continue

            for task_name in runtime.manifest.background_tasks:
                task = getattr(module, task_name, None)
                if not callable(task):
                    results.append(PluginOperationResult(action="background_task", success=False, message="task missing", payload={"plugin_id": current_plugin_id, "task": task_name}))
                    continue
                try:
                    output = self._safe_call(task, payload={}, config=runtime.config)
                    self.repository.update_health_success(current_plugin_id)
                    self.statistics.increment("background_tasks_run")
                    results.append(PluginOperationResult(action="background_task", success=True, payload={"plugin_id": current_plugin_id, "task": task_name, "output": output}))
                except Exception as exc:
                    self.repository.update_health_failure(current_plugin_id, str(exc))
                    self.statistics.increment("failed")
                    results.append(PluginOperationResult(action="background_task", success=False, message=str(exc), payload={"plugin_id": current_plugin_id, "task": task_name}))
        return results

    def run_due_scheduled_tasks(self, now: datetime | None = None) -> list[PluginOperationResult]:
        due = self.repository.next_due_scheduled_tasks(now=now)
        results: list[PluginOperationResult] = []

        for plugin_id, task_id in due:
            runtime = self.repository.get_runtime(plugin_id)
            module = self._loaded_modules.get(plugin_id)
            if runtime is None or module is None or not runtime.enabled:
                continue
            if "tasks:scheduled" not in runtime.manifest.permissions:
                continue

            task_meta = next((item for item in runtime.manifest.scheduled_tasks if item.task_id == task_id), None)
            if task_meta is None:
                continue

            func = getattr(module, task_meta.callable_name, None)
            if not callable(func):
                results.append(PluginOperationResult(action="scheduled_task", success=False, message="task missing", payload={"plugin_id": plugin_id, "task": task_id}))
                continue

            try:
                output = self._safe_call(func, payload={}, config=runtime.config)
                self.repository.schedule_task(plugin_id, task_id, task_meta.interval_seconds, now=now)
                self.repository.update_health_success(plugin_id)
                self.statistics.increment("scheduled_tasks_run")
                results.append(PluginOperationResult(action="scheduled_task", success=True, payload={"plugin_id": plugin_id, "task": task_id, "output": output}))
            except Exception as exc:
                self.repository.schedule_task(plugin_id, task_id, task_meta.interval_seconds, now=now)
                self.repository.update_health_failure(plugin_id, str(exc))
                self.statistics.increment("failed")
                results.append(PluginOperationResult(action="scheduled_task", success=False, message=str(exc), payload={"plugin_id": plugin_id, "task": task_id}))

        return results

    # ------------------------------------------------------------------
    # Settings/config and health
    # ------------------------------------------------------------------
    def update_config(self, plugin_id: str, config: dict[str, Any]) -> PluginOperationResult:
        runtime = self.repository.get_runtime(plugin_id)
        if runtime is None:
            return PluginOperationResult(action="config", success=False, message=f"Plugin not found: {plugin_id}")
        normalized = self.builder.normalize_config(runtime.manifest, config)
        self.repository.update_config(plugin_id, normalized)
        return PluginOperationResult(action="config", success=True, payload={"plugin_id": plugin_id, "config": normalized})

    def health(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for runtime in self.repository.list_runtimes():
            out[runtime.manifest.plugin_id] = {
                "status": runtime.health.status.value,
                "last_error": runtime.health.last_error,
                "last_checked_at": runtime.health.last_checked_at.isoformat(),
                "consecutive_failures": runtime.health.consecutive_failures,
                "consecutive_successes": runtime.health.consecutive_successes,
                "state": runtime.state.value,
                "enabled": runtime.enabled,
            }
        self.statistics.increment("health_checks")
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _import_plugin_module(self, manifest: PluginManifest) -> ModuleType:
        if manifest.plugin_directory is None:
            raise PluginLoadError(f"Missing plugin_directory for {manifest.plugin_id}")

        entrypoint = manifest.plugin_directory / manifest.entrypoint
        if not entrypoint.exists():
            raise PluginLoadError(f"Entrypoint not found: {entrypoint}")

        module_name = (
            f"plugin_runtime_{manifest.plugin_id}_{manifest.version.replace('.', '_')}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        )
        module = ModuleType(module_name)
        module.__file__ = str(entrypoint)
        sys.modules[module_name] = module
        try:
            source = entrypoint.read_text(encoding="utf-8")
            code = compile(source, str(entrypoint), "exec")
            exec(code, module.__dict__)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise PluginLoadError(f"Failed to execute plugin module {manifest.plugin_id}: {exc}") from exc

        startup = getattr(module, "startup", None)
        if callable(startup):
            self._safe_call(startup, payload={}, config=manifest.default_config)

        return module

    def _register_plugin_settings(self, runtime: PluginRuntime) -> None:
        if "settings:register" not in runtime.manifest.permissions:
            return
        normalized = self.builder.normalize_config(runtime.manifest, runtime.config)
        self.repository.update_config(runtime.manifest.plugin_id, normalized)

    def _schedule_plugin_tasks(self, runtime: PluginRuntime) -> None:
        if "tasks:scheduled" not in runtime.manifest.permissions:
            return
        for task in runtime.manifest.scheduled_tasks:
            self.repository.schedule_task(runtime.manifest.plugin_id, task.task_id, task.interval_seconds)

    def _safe_call(self, func: Callable[..., Any], *, payload: dict[str, Any], config: dict[str, Any], event_name: str | None = None) -> Any:
        sandbox_payload = deepcopy(payload)
        sandbox_config = deepcopy(config)
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_name": event_name,
            "app_version": self.app_version,
        }
        return func(payload=sandbox_payload, config=sandbox_config, context=context)
