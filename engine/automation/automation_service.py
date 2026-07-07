from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from engine.automation.automation_engine import AutomationEngine
from engine.automation.automation_models import (
    AutomationCondition,
    AutomationCheckpoint,
    AutomationOperationResult,
    AutomationRetryPolicy,
    AutomationScheduleType,
    AutomationTriggerType,
)
from engine.pipeline import PipelineJob, QueueManager, QueueType


class AutomationService:
    """Service facade wiring automation engine operations to SEARCH queue jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: AutomationEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or AutomationEngine(queue_manager=self.queue_manager)

    def process_automation_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: AutomationCheckpoint | None = None,
    ) -> AutomationOperationResult | None:
        metadata = job.metadata or {}
        if metadata.get("stage") != "automation":
            return None

        if checkpoint is not None and checkpoint.is_processed(str(job.id)):
            return None

        action = str(metadata.get("action", "run_due")).lower()
        result = self._dispatch(action=action, metadata=metadata)

        if checkpoint is not None and result is not None:
            checkpoint.add_processed(str(job.id))

        return result

    def process_automation_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: AutomationCheckpoint | None = None,
    ) -> list[AutomationOperationResult]:
        out: list[AutomationOperationResult] = []
        for job in jobs:
            result = self.process_automation_job(job, checkpoint=checkpoint)
            if result is not None:
                out.append(result)
        return out

    def _dispatch(self, *, action: str, metadata: dict[str, Any]) -> AutomationOperationResult | None:
        if action == "schedule":
            queue_type = QueueType(str(metadata.get("queue_type", QueueType.SEARCH.value)))
            schedule_type = AutomationScheduleType(str(metadata.get("schedule_type", AutomationScheduleType.ONE_SHOT.value)))
            trigger_type = AutomationTriggerType(str(metadata.get("trigger_type", AutomationTriggerType.SCHEDULED.value)))
            run_at = datetime.fromisoformat(metadata["run_at"]) if metadata.get("run_at") else None
            condition = None
            if metadata.get("condition"):
                condition_payload = dict(metadata["condition"])
                condition = AutomationCondition(
                    key=str(condition_payload.get("key", "")),
                    equals=str(condition_payload.get("equals", "")),
                )
            retry_policy_payload = dict(metadata.get("retry_policy", {}))
            retry_policy = AutomationRetryPolicy(
                max_retries=int(retry_policy_payload.get("max_retries", 0)),
                backoff_seconds=int(retry_policy_payload.get("backoff_seconds", 30)),
                exponential_backoff=bool(retry_policy_payload.get("exponential_backoff", True)),
            )

            scheduled = self.engine.schedule_job(
                job_id=str(metadata["job_id"]),
                name=str(metadata.get("name", metadata["job_id"])),
                action=str(metadata.get("automation_action", metadata.get("job_action", "run"))),
                queue_type=queue_type,
                priority=int(metadata.get("priority", 0)),
                schedule_type=schedule_type,
                trigger_type=trigger_type,
                run_at=run_at,
                interval_seconds=metadata.get("interval_seconds"),
                cron_expression=metadata.get("cron_expression"),
                dependencies=set(metadata.get("dependencies", [])),
                condition=condition,
                payload=dict(metadata.get("payload", {})),
                retry_policy=retry_policy,
            )
            return AutomationOperationResult(action="schedule", success=True, payload={"job": scheduled})

        if action == "schedule_delayed":
            queue_type = QueueType(str(metadata.get("queue_type", QueueType.SEARCH.value)))
            retry_policy_payload = dict(metadata.get("retry_policy", {}))
            retry_policy = AutomationRetryPolicy(
                max_retries=int(retry_policy_payload.get("max_retries", 0)),
                backoff_seconds=int(retry_policy_payload.get("backoff_seconds", 30)),
                exponential_backoff=bool(retry_policy_payload.get("exponential_backoff", True)),
            )
            scheduled = self.engine.schedule_delayed_job(
                job_id=str(metadata["job_id"]),
                name=str(metadata.get("name", metadata["job_id"])),
                action=str(metadata.get("automation_action", metadata.get("job_action", "run"))),
                queue_type=queue_type,
                priority=int(metadata.get("priority", 0)),
                delay_seconds=int(metadata.get("delay_seconds", 0)),
                payload=dict(metadata.get("payload", {})),
                retry_policy=retry_policy,
            )
            return AutomationOperationResult(action="schedule_delayed", success=True, payload={"job": scheduled})

        if action == "run_due":
            now = datetime.fromisoformat(metadata["now"]) if metadata.get("now") else datetime.now(timezone.utc)
            context = dict(metadata.get("context", {}))
            runs = self.engine.run_due(now=now, context=context)
            return AutomationOperationResult(action="run_due", success=True, payload={"runs": runs})

        if action == "trigger_manual":
            run = self.engine.trigger_manual(str(metadata["job_id"]), context=dict(metadata.get("context", {})))
            return AutomationOperationResult(action="trigger_manual", success=True, payload={"run": run})

        if action == "trigger_event":
            runs = self.engine.trigger_event(str(metadata.get("event_name", "")), payload=dict(metadata.get("payload", {})))
            return AutomationOperationResult(action="trigger_event", success=True, payload={"runs": runs})

        if action == "trigger_pipeline":
            queue_type = QueueType(str(metadata.get("queue_type", QueueType.SEARCH.value)))
            runs = self.engine.trigger_pipeline(queue_type, payload=dict(metadata.get("payload", {})))
            return AutomationOperationResult(action="trigger_pipeline", success=True, payload={"runs": runs})

        if action == "pause":
            return self.engine.pause(str(metadata["job_id"]))

        if action == "resume":
            return self.engine.resume(str(metadata["job_id"]))

        if action == "cancel":
            return self.engine.cancel(str(metadata["job_id"]))

        if action == "maintenance_defaults":
            jobs = self.engine.schedule_maintenance_defaults()
            return AutomationOperationResult(action="maintenance_defaults", success=True, payload={"jobs": jobs})

        if action == "progress":
            progress = self.engine.progress()
            return AutomationOperationResult(action="progress", success=True, payload={"progress": progress})

        if action == "history":
            history = self.engine.history()
            return AutomationOperationResult(action="history", success=True, payload={"history": history})

        return None

    def publish_automation_job(self, *, action: str, metadata: dict[str, Any] | None = None) -> PipelineJob:
        payload = {"stage": "automation", "action": action}
        if metadata:
            payload.update(metadata)
        job = PipelineJob(queue_type=QueueType.SEARCH, metadata=payload)
        return self.queue_manager.enqueue(QueueType.SEARCH, job)
