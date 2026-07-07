from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from engine.automation.automation_builder import AutomationBuilder
from engine.automation.automation_exceptions import AutomationValidationError
from engine.automation.automation_models import (
    AutomationCondition,
    AutomationJob,
    AutomationJobState,
    AutomationOperationResult,
    AutomationProgress,
    AutomationRetryPolicy,
    AutomationRunRecord,
    AutomationRunStatus,
    AutomationScheduleType,
    AutomationTriggerType,
)
from engine.automation.automation_statistics import AutomationStatistics
from engine.events.base_event import BaseEvent
from engine.events.event_dispatcher import EventDispatcher
from engine.logging import get_logger
from engine.pipeline.pipeline_models import PipelineJob, QueueType
from engine.pipeline.queue_manager import QueueManager
from engine.repositories.automation_repository import AutomationRepository


class AutomationEngine:
    """Schedules and queues deterministic automation jobs on existing pipeline infrastructure."""

    def __init__(
        self,
        *,
        repository: AutomationRepository | None = None,
        builder: AutomationBuilder | None = None,
        queue_manager: QueueManager | None = None,
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        self.repository = repository or AutomationRepository()
        self.builder = builder or AutomationBuilder()
        self.queue_manager = queue_manager or QueueManager()
        self.dispatcher = dispatcher or EventDispatcher()
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = AutomationStatistics()

    # ------------------------------------------------------------------
    # Job creation APIs
    # ------------------------------------------------------------------
    def schedule_job(
        self,
        *,
        job_id: str,
        name: str,
        action: str,
        queue_type: QueueType,
        priority: int,
        schedule_type: AutomationScheduleType,
        trigger_type: AutomationTriggerType,
        run_at: datetime | None = None,
        interval_seconds: int | None = None,
        cron_expression: str | None = None,
        dependencies: set[str] | None = None,
        condition: AutomationCondition | None = None,
        payload: dict[str, Any] | None = None,
        retry_policy: AutomationRetryPolicy | None = None,
    ) -> AutomationJob:
        job = self.builder.build_job(
            job_id=job_id,
            name=name,
            action=action,
            queue_type=queue_type,
            priority=priority,
            schedule_type=schedule_type,
            trigger_type=trigger_type,
            run_at=run_at,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            dependencies=dependencies,
            condition=condition,
            payload=payload,
            retry_policy=retry_policy,
        )
        saved = self.repository.upsert_job(job)
        self.statistics.increment("scheduled_jobs")
        return saved

    def schedule_delayed_job(
        self,
        *,
        job_id: str,
        name: str,
        action: str,
        queue_type: QueueType,
        priority: int,
        delay_seconds: int,
        payload: dict[str, Any] | None = None,
        retry_policy: AutomationRetryPolicy | None = None,
    ) -> AutomationJob:
        job = self.builder.build_delayed_job(
            job_id=job_id,
            name=name,
            action=action,
            queue_type=queue_type,
            priority=priority,
            delay_seconds=delay_seconds,
            payload=payload,
            retry_policy=retry_policy,
        )
        saved = self.repository.upsert_job(job)
        self.statistics.increment("scheduled_jobs")
        return saved

    def schedule_maintenance_defaults(self, now: datetime | None = None) -> list[AutomationJob]:
        base = now or datetime.now(timezone.utc)
        jobs = [
            self.schedule_job(
                job_id="maintenance_scan",
                name="Automatic Library Scan",
                action="scan_library",
                queue_type=QueueType.DISCOVERY,
                priority=60,
                schedule_type=AutomationScheduleType.RECURRING,
                trigger_type=AutomationTriggerType.SCHEDULED,
                interval_seconds=3600,
                payload={"stage": "automation", "kind": "library_scan"},
            ),
            self.schedule_job(
                job_id="maintenance_thumbnail",
                name="Automatic Thumbnail Regeneration",
                action="regenerate_thumbnails",
                queue_type=QueueType.THUMBNAIL,
                priority=50,
                schedule_type=AutomationScheduleType.RECURRING,
                trigger_type=AutomationTriggerType.SCHEDULED,
                interval_seconds=7200,
                payload={"stage": "automation", "kind": "thumbnail_regen"},
            ),
            self.schedule_job(
                job_id="maintenance_embedding",
                name="Automatic Embedding Generation",
                action="generate_embeddings",
                queue_type=QueueType.EMBEDDING,
                priority=55,
                schedule_type=AutomationScheduleType.RECURRING,
                trigger_type=AutomationTriggerType.SCHEDULED,
                interval_seconds=7200,
                payload={"stage": "automation", "kind": "embedding_generation"},
            ),
            self.schedule_job(
                job_id="maintenance_metadata",
                name="Automatic Metadata Refresh",
                action="refresh_metadata",
                queue_type=QueueType.METADATA,
                priority=45,
                schedule_type=AutomationScheduleType.RECURRING,
                trigger_type=AutomationTriggerType.SCHEDULED,
                interval_seconds=10800,
                payload={"stage": "automation", "kind": "metadata_refresh"},
            ),
            self.schedule_job(
                job_id="maintenance_recognition_retry",
                name="Automatic Recognition Retries",
                action="retry_recognition",
                queue_type=QueueType.RECOGNITION,
                priority=65,
                schedule_type=AutomationScheduleType.RECURRING,
                trigger_type=AutomationTriggerType.SCHEDULED,
                interval_seconds=5400,
                payload={"stage": "automation", "kind": "recognition_retry"},
            ),
            self.schedule_job(
                job_id="maintenance_integrity",
                name="Automatic Integrity Verification",
                action="verify_integrity",
                queue_type=QueueType.TRANSACTION,
                priority=70,
                schedule_type=AutomationScheduleType.RECURRING,
                trigger_type=AutomationTriggerType.SCHEDULED,
                interval_seconds=14400,
                payload={"stage": "automation", "kind": "integrity_verification"},
            ),
            self.schedule_job(
                job_id="maintenance_cleanup",
                name="Automatic Cleanup Jobs",
                action="cleanup_jobs",
                queue_type=QueueType.TRANSACTION,
                priority=40,
                schedule_type=AutomationScheduleType.RECURRING,
                trigger_type=AutomationTriggerType.SCHEDULED,
                interval_seconds=21600,
                payload={"stage": "automation", "kind": "cleanup"},
            ),
        ]
        self.statistics.increment("maintenance_jobs_created", len(jobs))
        return jobs

    # ------------------------------------------------------------------
    # Scheduler execution
    # ------------------------------------------------------------------
    def run_due(self, now: datetime | None = None, context: dict[str, Any] | None = None) -> list[AutomationRunRecord]:
        current = now or datetime.now(timezone.utc)
        evaluation_context = dict(context or {})
        jobs = self.builder.resolve_dependency_order(self.repository.due_jobs(current))
        runs: list[AutomationRunRecord] = []

        for job in jobs:
            run = self._run_job(job, trigger=AutomationTriggerType.SCHEDULED, now=current, context=evaluation_context)
            runs.append(run)

        self.statistics.increment("history_entries", len(runs))
        return runs

    def trigger_manual(self, job_id: str, context: dict[str, Any] | None = None) -> AutomationRunRecord:
        job = self.repository.get_job(job_id)
        if job is None:
            raise AutomationValidationError(f"Unknown job_id: {job_id}")
        self.statistics.increment("manual_triggers")
        run = self._run_job(job, trigger=AutomationTriggerType.MANUAL, now=datetime.now(timezone.utc), context=dict(context or {}))
        self.statistics.increment("history_entries")
        return run

    def trigger_event(self, event_name: str, payload: dict[str, Any] | None = None) -> list[AutomationRunRecord]:
        base = datetime.now(timezone.utc)
        context = dict(payload or {})
        context["event_name"] = event_name

        matches = [
            item
            for item in self.repository.list_jobs()
            if item.trigger_type is AutomationTriggerType.EVENT
            and str(item.payload.get("event_name", "")) == event_name
            and item.state is AutomationJobState.ACTIVE
        ]

        runs = [self._run_job(item, trigger=AutomationTriggerType.EVENT, now=base, context=context) for item in self.builder.resolve_dependency_order(matches)]
        self.statistics.increment("event_triggers", len(runs))
        self.statistics.increment("history_entries", len(runs))
        return runs

    def trigger_pipeline(self, queue_type: QueueType, payload: dict[str, Any] | None = None) -> list[AutomationRunRecord]:
        base = datetime.now(timezone.utc)
        context = dict(payload or {})
        context["queue_type"] = queue_type.value

        matches = [
            item
            for item in self.repository.list_jobs()
            if item.trigger_type is AutomationTriggerType.PIPELINE
            and str(item.payload.get("queue_type", "")) == queue_type.value
            and item.state is AutomationJobState.ACTIVE
        ]

        runs = [self._run_job(item, trigger=AutomationTriggerType.PIPELINE, now=base, context=context) for item in self.builder.resolve_dependency_order(matches)]
        self.statistics.increment("pipeline_triggers", len(runs))
        self.statistics.increment("history_entries", len(runs))
        return runs

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------
    def pause(self, job_id: str) -> AutomationOperationResult:
        updated = self.repository.set_job_state(job_id, AutomationJobState.PAUSED)
        if updated is None:
            return AutomationOperationResult(action="pause", success=False, message=f"Unknown job_id: {job_id}")
        self.statistics.increment("paused_jobs")
        return AutomationOperationResult(action="pause", success=True, payload={"job_id": job_id})

    def resume(self, job_id: str) -> AutomationOperationResult:
        updated = self.repository.set_job_state(job_id, AutomationJobState.ACTIVE)
        if updated is None:
            return AutomationOperationResult(action="resume", success=False, message=f"Unknown job_id: {job_id}")
        self.statistics.increment("resumed_jobs")
        return AutomationOperationResult(action="resume", success=True, payload={"job_id": job_id})

    def cancel(self, job_id: str) -> AutomationOperationResult:
        updated = self.repository.set_job_state(job_id, AutomationJobState.CANCELLED)
        if updated is None:
            return AutomationOperationResult(action="cancel", success=False, message=f"Unknown job_id: {job_id}")
        self.statistics.increment("cancelled_jobs")
        return AutomationOperationResult(action="cancel", success=True, payload={"job_id": job_id})

    def progress(self) -> AutomationProgress:
        jobs = self.repository.list_jobs()
        return AutomationProgress(
            total_jobs=len(jobs),
            active_jobs=len([item for item in jobs if item.state is AutomationJobState.ACTIVE]),
            paused_jobs=len([item for item in jobs if item.state is AutomationJobState.PAUSED]),
            cancelled_jobs=len([item for item in jobs if item.state is AutomationJobState.CANCELLED]),
            completed_jobs=len([item for item in jobs if item.state is AutomationJobState.COMPLETED]),
            failed_jobs=len([item for item in jobs if item.state is AutomationJobState.FAILED]),
        )

    def history(self) -> list[AutomationRunRecord]:
        return self.repository.list_history()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _run_job(
        self,
        job: AutomationJob,
        *,
        trigger: AutomationTriggerType,
        now: datetime,
        context: dict[str, Any],
    ) -> AutomationRunRecord:
        snapshot = self.repository.get_job(job.job_id)
        if snapshot is None:
            raise AutomationValidationError(f"Unknown job_id: {job.job_id}")

        if snapshot.state is AutomationJobState.CANCELLED:
            record = self._record_run(snapshot, trigger=trigger, status=AutomationRunStatus.SKIPPED, started_at=now, finished_at=now, error_message="cancelled")
            self.repository.append_history(record)
            self.statistics.increment("skipped_runs")
            return record

        if snapshot.state is AutomationJobState.PAUSED:
            record = self._record_run(snapshot, trigger=trigger, status=AutomationRunStatus.SKIPPED, started_at=now, finished_at=now, error_message="paused")
            self.repository.append_history(record)
            self.statistics.increment("skipped_runs")
            return record

        if not self.builder.condition_matches(snapshot.condition, context):
            record = self._record_run(snapshot, trigger=trigger, status=AutomationRunStatus.SKIPPED, started_at=now, finished_at=now, error_message="condition")
            self.repository.append_history(record)
            self.statistics.increment("skipped_runs")
            return record

        if not self._dependencies_satisfied(snapshot):
            record = self._record_run(snapshot, trigger=trigger, status=AutomationRunStatus.SKIPPED, started_at=now, finished_at=now, error_message="dependencies")
            self.repository.append_history(record)
            self.statistics.increment("skipped_runs")
            return record

        started_at = now
        try:
            pipeline_job = PipelineJob(
                queue_type=snapshot.queue_type,
                priority=snapshot.priority,
                source_path=snapshot.payload.get("source_path"),
                metadata={
                    **dict(snapshot.payload),
                    "stage": "automation",
                    "automation_job_id": snapshot.job_id,
                    "automation_action": snapshot.action,
                    "trigger": trigger.value,
                },
            )
            queued_job = self.queue_manager.enqueue(snapshot.queue_type, pipeline_job)

            finished_at = datetime.now(timezone.utc)
            next_run = self.builder.next_run_after_success(snapshot, finished_at)
            new_state = AutomationJobState.COMPLETED if next_run is None else AutomationJobState.ACTIVE
            self.repository.update_job_fields(
                snapshot.job_id,
                last_run_at=finished_at,
                next_run_at=next_run,
                retries=0,
                successes=snapshot.successes + 1,
                state=new_state,
                last_error=None,
            )

            record = self._record_run(
                snapshot,
                trigger=trigger,
                status=AutomationRunStatus.QUEUED,
                started_at=started_at,
                finished_at=finished_at,
                pipeline_job_id=str(queued_job.id),
            )
            self.repository.append_history(record)
            self.statistics.increment("queued_runs")
            return record

        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            retries = snapshot.retries + 1
            failures = snapshot.failures + 1
            can_retry = retries <= snapshot.retry_policy.max_retries

            if can_retry:
                next_run = self.builder.next_run_after_failure(snapshot, finished_at)
                new_state = AutomationJobState.ACTIVE
                self.statistics.increment("retry_attempts")
            else:
                next_run = None
                new_state = AutomationJobState.FAILED

            self.repository.update_job_fields(
                snapshot.job_id,
                retries=retries,
                failures=failures,
                last_error=str(exc),
                next_run_at=next_run,
                state=new_state,
                last_run_at=finished_at,
            )
            record = self._record_run(
                snapshot,
                trigger=trigger,
                status=AutomationRunStatus.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                error_message=str(exc),
                attempt=retries,
            )
            self.repository.append_history(record)
            self.statistics.increment("failed_runs")
            return record

    def _dependencies_satisfied(self, job: AutomationJob) -> bool:
        for dep in sorted(job.dependencies):
            dep_job = self.repository.get_job(dep)
            if dep_job is None:
                continue
            if dep_job.state not in {AutomationJobState.COMPLETED, AutomationJobState.ACTIVE}:
                return False
            if not self.repository.has_success(dep):
                return False
        return True

    def _record_run(
        self,
        job: AutomationJob,
        *,
        trigger: AutomationTriggerType,
        status: AutomationRunStatus,
        started_at: datetime,
        finished_at: datetime,
        pipeline_job_id: str | None = None,
        error_message: str | None = None,
        attempt: int = 0,
    ) -> AutomationRunRecord:
        return AutomationRunRecord(
            run_id=str(uuid4()),
            job_id=job.job_id,
            status=status,
            trigger=trigger,
            started_at=started_at,
            finished_at=finished_at,
            queue_type=job.queue_type,
            pipeline_job_id=pipeline_job_id,
            error_message=error_message,
            attempt=attempt,
        )
