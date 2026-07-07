from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.plugin_system import (
    PluginBuilder,
    PluginDependencyError,
    PluginEngine,
    PluginHookType,
    PluginService,
    PluginWorker,
)


def _write_plugin(root: Path, plugin_id: str, manifest: dict, module_source: str) -> Path:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (plugin_dir / manifest.get("entrypoint", "plugin.py")).write_text(module_source, encoding="utf-8")
    return plugin_dir


@pytest.fixture()
def plugin_root(tmp_path: Path) -> Path:
    return tmp_path / "plugins"


@pytest.fixture()
def engine() -> PluginEngine:
    return PluginEngine(app_version="0.1.0")


def test_discovery_registration_loading_unloading(plugin_root: Path, engine: PluginEngine) -> None:
    _write_plugin(
        plugin_root,
        "base_plugin",
        {
            "plugin_id": "base_plugin",
            "name": "Base Plugin",
            "version": "1.0.0",
            "permissions": ["commands:execute"],
            "commands": {"ping": "command_ping"},
        },
        """
def command_ping(payload, config, context):
    return {\"pong\": True}
""",
    )

    _write_plugin(
        plugin_root,
        "ext_plugin",
        {
            "plugin_id": "ext_plugin",
            "name": "Extension Plugin",
            "version": "1.0.0",
            "dependencies": [{"plugin_id": "base_plugin", "version_constraint": ">=1.0.0"}],
            "permissions": ["commands:execute"],
            "commands": {"ping": "command_ping"},
        },
        """
def command_ping(payload, config, context):
    return {\"pong\": \"ext\"}
""",
    )

    discovery = engine.discover(plugin_root)
    assert len(discovery.discovered) == 2
    runtimes = engine.register(discovery.discovered)
    assert [item.manifest.plugin_id for item in runtimes] == ["base_plugin", "ext_plugin"]

    loaded = engine.load_all()
    assert all(item.success for item in loaded)

    cmd = engine.execute_command("base_plugin", "ping")
    assert cmd.success is True
    assert cmd.payload == {"pong": True}

    unloaded = engine.unload_plugin("base_plugin")
    assert unloaded.success is True


def test_version_compatibility_check(plugin_root: Path, engine: PluginEngine) -> None:
    _write_plugin(
        plugin_root,
        "incompatible",
        {
            "plugin_id": "incompatible",
            "name": "Incompatible",
            "version": "1.0.0",
            "app_version": ">=9.0.0",
            "permissions": [],
        },
        """
""",
    )

    discovery = engine.discover(plugin_root)
    assert len(discovery.discovered) == 0
    assert len(discovery.failed) == 1


def test_dependency_cycle_detection(plugin_root: Path) -> None:
    builder = PluginBuilder()

    a = builder.parse_manifest_payload(
        {
            "plugin_id": "a",
            "name": "A",
            "version": "1.0.0",
            "dependencies": ["b"],
            "permissions": [],
        }
    )
    b = builder.parse_manifest_payload(
        {
            "plugin_id": "b",
            "name": "B",
            "version": "1.0.0",
            "dependencies": ["a"],
            "permissions": [],
        }
    )

    with pytest.raises(PluginDependencyError):
        builder.resolve_load_order([a, b])


def test_hot_reload(plugin_root: Path, engine: PluginEngine) -> None:
    _write_plugin(
        plugin_root,
        "reloadable",
        {
            "plugin_id": "reloadable",
            "name": "Reloadable",
            "version": "1.0.0",
            "permissions": ["commands:execute"],
            "commands": {"value": "command_value"},
        },
        """
def command_value(payload, config, context):
    return {\"value\": 1}
""",
    )

    discovery = engine.discover(plugin_root)
    engine.register(discovery.discovered)
    engine.load_all()

    first = engine.execute_command("reloadable", "value")
    assert first.payload == {"value": 1}

    entrypoint = plugin_root / "reloadable" / "plugin.py"
    entrypoint.write_text(
        """
def command_value(payload, config, context):
    return {\"value\": 2}
""",
        encoding="utf-8",
    )

    reloaded = engine.hot_reload("reloadable")
    assert reloaded.success is True

    second = engine.execute_command("reloadable", "value")
    assert second.payload == {"value": 2}


def test_event_dispatch_and_hook_execution(plugin_root: Path, engine: PluginEngine) -> None:
    _write_plugin(
        plugin_root,
        "hooker",
        {
            "plugin_id": "hooker",
            "name": "Hooker",
            "version": "1.0.0",
            "permissions": ["events:subscribe", "hooks:pipeline", "hooks:search"],
            "subscribed_events": ["job.finished"],
            "hooks": {"pipeline": "pipeline_hook", "search": "search_hook"},
        },
        """
def on_event(payload, config, context):
    return {\"received\": context.get(\"event_name\")}

def pipeline_hook(payload, config, context):
    return {\"pipeline\": payload.get(\"value\", 0) + 1}

def search_hook(payload, config, context):
    return {\"search\": payload.get(\"query\", \"\").upper()}
""",
    )

    discovery = engine.discover(plugin_root)
    engine.register(discovery.discovered)
    engine.load_all()

    event_results = engine.dispatch_event("job.finished", {"id": 10})
    assert len(event_results) == 1
    assert event_results[0].success is True

    pipeline_results = engine.run_hook(PluginHookType.PIPELINE, {"value": 3})
    assert len(pipeline_results) == 1
    assert pipeline_results[0].payload == {"pipeline": 4}

    search_results = engine.run_hook(PluginHookType.SEARCH, {"query": "abc"})
    assert search_results[0].payload == {"search": "ABC"}


def test_failure_isolation(plugin_root: Path, engine: PluginEngine) -> None:
    _write_plugin(
        plugin_root,
        "good",
        {
            "plugin_id": "good",
            "name": "Good",
            "version": "1.0.0",
            "permissions": ["hooks:metadata"],
            "hooks": {"metadata": "metadata_hook"},
        },
        """
def metadata_hook(payload, config, context):
    return {\"ok\": True}
""",
    )

    _write_plugin(
        plugin_root,
        "bad",
        {
            "plugin_id": "bad",
            "name": "Bad",
            "version": "1.0.0",
            "permissions": ["hooks:metadata"],
            "hooks": {"metadata": "metadata_hook"},
        },
        """
def metadata_hook(payload, config, context):
    raise RuntimeError(\"boom\")
""",
    )

    discovery = engine.discover(plugin_root)
    engine.register(discovery.discovered)
    engine.load_all()

    results = engine.run_hook(PluginHookType.METADATA, {"x": 1})
    by_id = {item.plugin_id: item for item in results}
    assert by_id["good"].success is True
    assert by_id["bad"].success is False


def test_configuration_and_statistics(plugin_root: Path, engine: PluginEngine) -> None:
    _write_plugin(
        plugin_root,
        "configurable",
        {
            "plugin_id": "configurable",
            "name": "Configurable",
            "version": "1.0.0",
            "permissions": ["settings:register", "commands:execute"],
            "settings_schema": {"threshold": "number", "enabled": "bool"},
            "default_config": {"threshold": 0.4, "enabled": True},
            "commands": {"read_config": "read_config"},
        },
        """
def read_config(payload, config, context):
    return {\"threshold\": config.get(\"threshold\"), \"enabled\": config.get(\"enabled\")}
""",
    )

    discovery = engine.discover(plugin_root)
    engine.register(discovery.discovered)
    engine.load_all()

    update = engine.update_config("configurable", {"threshold": 0.9})
    assert update.success is True

    cmd = engine.execute_command("configurable", "read_config")
    assert cmd.success is True
    assert cmd.payload == {"threshold": 0.9, "enabled": True}

    health = engine.health()
    assert "configurable" in health

    assert engine.statistics.discovered >= 1
    assert engine.statistics.registered >= 1
    assert engine.statistics.loaded >= 1
    assert engine.statistics.commands_executed >= 1
    assert engine.statistics.health_checks >= 1


def test_background_and_scheduled_tasks(plugin_root: Path, engine: PluginEngine) -> None:
    _write_plugin(
        plugin_root,
        "tasker",
        {
            "plugin_id": "tasker",
            "name": "Tasker",
            "version": "1.0.0",
            "permissions": ["tasks:background", "tasks:scheduled"],
            "background_tasks": ["background"],
            "scheduled_tasks": [{"task_id": "tick", "callable": "scheduled", "interval_seconds": 5}],
        },
        """
def background(payload, config, context):
    return {\"background\": True}

def scheduled(payload, config, context):
    return {\"scheduled\": True}
""",
    )

    discovery = engine.discover(plugin_root)
    engine.register(discovery.discovered)
    engine.load_all()

    bg_results = engine.run_background_tasks("tasker")
    assert len(bg_results) == 1
    assert bg_results[0].success is True

    now = datetime.now(timezone.utc) + timedelta(seconds=10)
    scheduled_results = engine.run_due_scheduled_tasks(now=now)
    assert len(scheduled_results) == 1
    assert scheduled_results[0].success is True


def test_plugin_worker_cancellation_resume(plugin_root: Path) -> None:
    _write_plugin(
        plugin_root,
        "worker_plugin",
        {
            "plugin_id": "worker_plugin",
            "name": "Worker Plugin",
            "version": "1.0.0",
            "permissions": ["commands:execute"],
            "commands": {"ping": "ping"},
        },
        """
def ping(payload, config, context):
    return {\"pong\": True}
""",
    )

    queue_manager = QueueManager()
    engine = PluginEngine(app_version="0.1.0")
    service = PluginService(queue_manager=queue_manager, engine=engine)
    worker = PluginWorker(queue_manager=queue_manager, service=service)

    discover_job = PipelineJob(
        source_path=str(plugin_root),
        queue_type=QueueType.SEARCH,
        metadata={"stage": "plugin_system", "action": "discover"},
    )

    worker.cancel(str(discover_job.id))
    cancelled = worker.process_jobs([discover_job])
    assert cancelled == []

    worker.resume(str(discover_job.id))
    resumed = worker.process_jobs([discover_job])
    assert len(resumed) == 1
    assert resumed[0].success is True

    load_job = PipelineJob(
        source_path=str(plugin_root),
        queue_type=QueueType.SEARCH,
        metadata={"stage": "plugin_system", "action": "load_all"},
    )
    loaded = worker.process_jobs([load_job])
    assert len(loaded) == 1
    assert loaded[0].success is True
