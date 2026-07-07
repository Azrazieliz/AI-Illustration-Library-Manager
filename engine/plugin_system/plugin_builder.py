from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from engine.plugin_system.plugin_exceptions import (
    PluginCompatibilityError,
    PluginDependencyError,
    PluginManifestError,
)
from engine.plugin_system.plugin_models import (
    PluginDependency,
    PluginHookType,
    PluginManifest,
    PluginScheduledTask,
)


class PluginBuilder:
    """Builds manifests and deterministic dependency/load plans."""

    _ALLOWED_PERMISSIONS = {
        "events:subscribe",
        "hooks:pipeline",
        "hooks:search",
        "hooks:recognition",
        "hooks:metadata",
        "hooks:export",
        "hooks:import",
        "commands:execute",
        "settings:register",
        "tasks:background",
        "tasks:scheduled",
    }

    def parse_manifest_file(self, manifest_path: Path) -> PluginManifest:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PluginManifestError(f"Failed to parse manifest: {manifest_path}") from exc
        manifest = self.parse_manifest_payload(payload)
        manifest.plugin_directory = manifest_path.parent
        return manifest

    def parse_manifest_payload(self, payload: dict[str, Any]) -> PluginManifest:
        plugin_id = str(payload.get("plugin_id", "")).strip()
        name = str(payload.get("name", "")).strip()
        version = str(payload.get("version", "")).strip()
        if not plugin_id or not name or not version:
            raise PluginManifestError("plugin_id, name, and version are required")

        deps = []
        for item in payload.get("dependencies", []):
            if isinstance(item, str):
                deps.append(PluginDependency(plugin_id=item, version_constraint=""))
            else:
                deps.append(
                    PluginDependency(
                        plugin_id=str(item.get("plugin_id", "")).strip(),
                        version_constraint=str(item.get("version_constraint", "")).strip(),
                    )
                )

        hooks: dict[PluginHookType, str] = {}
        for key, value in dict(payload.get("hooks", {})).items():
            hooks[PluginHookType(str(key))] = str(value)

        commands = {str(k): str(v) for k, v in dict(payload.get("commands", {})).items()}

        scheduled: list[PluginScheduledTask] = []
        for task in payload.get("scheduled_tasks", []):
            scheduled.append(
                PluginScheduledTask(
                    task_id=str(task.get("task_id", "")).strip(),
                    callable_name=str(task.get("callable", "")).strip(),
                    interval_seconds=max(1, int(task.get("interval_seconds", 60))),
                )
            )

        permissions = {str(item).strip() for item in payload.get("permissions", []) if str(item).strip()}
        unknown = permissions.difference(self._ALLOWED_PERMISSIONS)
        if unknown:
            raise PluginManifestError(f"Unknown permissions: {sorted(unknown)}")

        return PluginManifest(
            plugin_id=plugin_id,
            name=name,
            version=version,
            entrypoint=str(payload.get("entrypoint", "plugin.py")).strip() or "plugin.py",
            api_version=str(payload.get("api_version", "1.0")).strip() or "1.0",
            app_version=str(payload.get("app_version", ">=0.1.0")).strip() or ">=0.1.0",
            dependencies=deps,
            enabled_by_default=bool(payload.get("enabled_by_default", True)),
            permissions=permissions,
            subscribed_events={str(item).strip() for item in payload.get("subscribed_events", []) if str(item).strip()},
            hooks=hooks,
            commands=commands,
            settings_schema=dict(payload.get("settings_schema", {})),
            default_config=dict(payload.get("default_config", {})),
            background_tasks=[str(item).strip() for item in payload.get("background_tasks", []) if str(item).strip()],
            scheduled_tasks=[item for item in scheduled if item.task_id and item.callable_name],
            sandboxed=bool(payload.get("sandboxed", True)),
        )

    def check_version_compatibility(self, manifest: PluginManifest, app_version: str) -> None:
        if not self._matches_constraint(app_version, manifest.app_version):
            raise PluginCompatibilityError(
                f"Plugin {manifest.plugin_id} requires app_version {manifest.app_version}, got {app_version}"
            )

    def resolve_load_order(self, manifests: list[PluginManifest]) -> list[PluginManifest]:
        by_id = {item.plugin_id: item for item in manifests}
        indegree = {item.plugin_id: 0 for item in manifests}
        graph: dict[str, set[str]] = {item.plugin_id: set() for item in manifests}

        for manifest in manifests:
            for dep in manifest.dependencies:
                if dep.plugin_id not in by_id:
                    raise PluginDependencyError(f"Missing dependency {dep.plugin_id} for {manifest.plugin_id}")
                dep_manifest = by_id[dep.plugin_id]
                if dep.version_constraint and not self._matches_constraint(dep_manifest.version, dep.version_constraint):
                    raise PluginDependencyError(
                        f"Dependency version mismatch for {manifest.plugin_id}: {dep.plugin_id} {dep.version_constraint}"
                    )
                if manifest.plugin_id not in graph[dep.plugin_id]:
                    graph[dep.plugin_id].add(manifest.plugin_id)
                    indegree[manifest.plugin_id] += 1

        ready = sorted([node for node, degree in indegree.items() if degree == 0])
        order: list[str] = []

        while ready:
            node = ready.pop(0)
            order.append(node)
            for neighbor in sorted(graph[node]):
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    ready.append(neighbor)
                    ready.sort()

        if len(order) != len(manifests):
            raise PluginDependencyError("Dependency cycle detected")

        return [by_id[item] for item in order]

    def normalize_config(self, manifest: PluginManifest, config: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(manifest.default_config)
        if config:
            merged.update(config)
        for key in manifest.settings_schema:
            if key not in merged:
                merged[key] = None
        return merged

    def serialize_manifest(self, manifest: PluginManifest) -> dict[str, Any]:
        payload = asdict(manifest)
        payload["hooks"] = {key.value: value for key, value in manifest.hooks.items()}
        payload["permissions"] = sorted(manifest.permissions)
        payload["subscribed_events"] = sorted(manifest.subscribed_events)
        return payload

    def _matches_constraint(self, version: str, constraint: str) -> bool:
        version_tuple = self._parse_version(version)
        rules = [item.strip() for item in str(constraint).split(",") if item.strip()]
        if not rules:
            return True

        for rule in rules:
            if rule.startswith(">="):
                if version_tuple < self._parse_version(rule[2:]):
                    return False
            elif rule.startswith(">"):
                if version_tuple <= self._parse_version(rule[1:]):
                    return False
            elif rule.startswith("<="):
                if version_tuple > self._parse_version(rule[2:]):
                    return False
            elif rule.startswith("<"):
                if version_tuple >= self._parse_version(rule[1:]):
                    return False
            elif rule.startswith("=="):
                if version_tuple != self._parse_version(rule[2:]):
                    return False
            else:
                if version_tuple != self._parse_version(rule):
                    return False
        return True

    def _parse_version(self, value: str) -> tuple[int, int, int]:
        parts = [item for item in str(value).strip().split(".") if item]
        if not parts:
            raise PluginManifestError(f"Invalid version: {value}")
        normalized = [int(item) for item in parts[:3]]
        while len(normalized) < 3:
            normalized.append(0)
        return tuple(normalized)
