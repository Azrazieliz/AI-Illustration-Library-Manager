from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.plugin_system.plugin_engine import PluginEngine
from engine.plugin_system.plugin_models import PluginCheckpoint, PluginHookType, PluginOperationResult


class PluginService:
    """Service facade connecting plugin operations to pipeline jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: PluginEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or PluginEngine()

    def process_plugin_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: PluginCheckpoint | None = None,
    ) -> PluginOperationResult | None:
        metadata = job.metadata or {}
        if metadata.get("stage") != "plugin_system":
            return None

        if checkpoint is not None and checkpoint.is_processed(str(job.id)):
            return None

        action = str(metadata.get("action", "discover")).strip().lower()
        result = self._dispatch(action=action, metadata=metadata, source_path=job.source_path)

        if checkpoint is not None and result is not None:
            checkpoint.add_processed(str(job.id))

        return result

    def process_plugin_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: PluginCheckpoint | None = None,
    ) -> list[PluginOperationResult]:
        out: list[PluginOperationResult] = []
        for job in jobs:
            result = self.process_plugin_job(job, checkpoint=checkpoint)
            if result is not None:
                out.append(result)
        return out

    def _dispatch(self, *, action: str, metadata: dict[str, Any], source_path: str | None) -> PluginOperationResult | None:
        if action == "discover":
            root = Path(source_path or metadata.get("plugin_root", "plugins"))
            discovery = self.engine.discover(root)
            registered = self.engine.register(discovery.discovered)
            return PluginOperationResult(
                action="discover",
                success=True,
                payload={
                    "discovered": len(discovery.discovered),
                    "failed": dict(discovery.failed),
                    "registered": len(registered),
                },
            )

        if action == "load_all":
            results = self.engine.load_all()
            return PluginOperationResult(
                action="load_all",
                success=all(item.success for item in results) if results else True,
                payload={"results": results},
            )

        if action == "unload":
            plugin_id = str(metadata.get("plugin_id", "")).strip()
            result = self.engine.unload_plugin(plugin_id)
            return result

        if action == "hot_reload":
            plugin_id = str(metadata.get("plugin_id", "")).strip()
            result = self.engine.hot_reload(plugin_id)
            return result

        if action == "enable":
            plugin_id = str(metadata.get("plugin_id", "")).strip()
            result = self.engine.enable_plugin(plugin_id)
            return result

        if action == "disable":
            plugin_id = str(metadata.get("plugin_id", "")).strip()
            result = self.engine.disable_plugin(plugin_id)
            return result

        if action == "event":
            event_name = str(metadata.get("event_name", "")).strip()
            payload = dict(metadata.get("payload", {}))
            results = self.engine.dispatch_event(event_name, payload)
            return PluginOperationResult(action="event", success=True, payload={"results": results})

        if action == "hook":
            hook_type = PluginHookType(str(metadata.get("hook_type", "pipeline")))
            payload = dict(metadata.get("payload", {}))
            results = self.engine.run_hook(hook_type, payload)
            return PluginOperationResult(action="hook", success=True, payload={"results": results})

        if action == "command":
            plugin_id = str(metadata.get("plugin_id", "")).strip()
            command = str(metadata.get("command", "")).strip()
            payload = dict(metadata.get("payload", {}))
            result = self.engine.execute_command(plugin_id, command, payload)
            return PluginOperationResult(action="command", success=result.success, payload={"result": result}, message=result.error or "")

        if action == "background":
            plugin_id = metadata.get("plugin_id")
            results = self.engine.run_background_tasks(plugin_id=str(plugin_id) if plugin_id else None)
            return PluginOperationResult(action="background", success=True, payload={"results": results})

        if action == "scheduled":
            now = datetime.fromisoformat(metadata["now"]) if metadata.get("now") else datetime.now(timezone.utc)
            results = self.engine.run_due_scheduled_tasks(now=now)
            return PluginOperationResult(action="scheduled", success=True, payload={"results": results})

        if action == "config":
            plugin_id = str(metadata.get("plugin_id", "")).strip()
            config = dict(metadata.get("config", {}))
            result = self.engine.update_config(plugin_id, config)
            return result

        if action == "health":
            payload = self.engine.health()
            return PluginOperationResult(action="health", success=True, payload={"health": payload})

        return None

    def publish_plugin_job(self, *, action: str, plugin_root: str | None = None, metadata: dict[str, Any] | None = None) -> PipelineJob:
        job_metadata = {"stage": "plugin_system", "action": action}
        if metadata:
            job_metadata.update(metadata)
        job = PipelineJob(
            source_path=plugin_root,
            queue_type=QueueType.SEARCH,
            metadata=job_metadata,
        )
        return self.queue_manager.enqueue(QueueType.SEARCH, job)
