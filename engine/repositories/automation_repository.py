from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from engine.automation.automation_models import AutomationJob, AutomationJobState, AutomationRunRecord, AutomationRunStatus
from engine.automation.automation_models import AutomationCondition, AutomationRetryPolicy, AutomationScheduleType, AutomationTriggerType
from engine.database.models.automation import AutomationJobRecord as AutomationJobRow
from engine.database.models.automation import AutomationRunRecord as AutomationRunRow
from engine.database.session import session_scope
from engine.pipeline.pipeline_models import QueueType


class AutomationRepository:
    """Transactional persistence gateway for automation schedules and execution history."""

    def upsert_job(self, job: AutomationJob) -> AutomationJob:
        with session_scope() as session:
            row = session.scalar(select(AutomationJobRow).where(AutomationJobRow.job_id == job.job_id))
            created = row is None
            if row is None:
                row = AutomationJobRow(job_id=job.job_id)
                session.add(row)
            self._write_job(row, job, created=created)
            session.flush()
            return self._to_job(row)

    def get_job(self, job_id: str) -> AutomationJob | None:
        with session_scope() as session:
            row = session.scalar(select(AutomationJobRow).where(AutomationJobRow.job_id == str(job_id)))
            return None if row is None else self._to_job(row)

    def list_jobs(self) -> list[AutomationJob]:
        with session_scope() as session:
            rows = list(session.scalars(select(AutomationJobRow).order_by(AutomationJobRow.job_id)))
            return [self._to_job(row) for row in rows]

    def remove_job(self, job_id: str) -> bool:
        with session_scope() as session:
            row = session.scalar(select(AutomationJobRow).where(AutomationJobRow.job_id == str(job_id)))
            if row is None:
                return False
            session.delete(row)
            return True

    def set_job_state(self, job_id: str, state: AutomationJobState) -> AutomationJob | None:
        return self.update_job_fields(job_id, state=state)

    def update_job_fields(self, job_id: str, **changes: Any) -> AutomationJob | None:
        invalid = set(changes).difference(self._MUTABLE_FIELDS)
        if invalid:
            raise ValueError(f"Unsupported automation job fields: {', '.join(sorted(invalid))}")
        with session_scope() as session:
            row = session.scalar(select(AutomationJobRow).where(AutomationJobRow.job_id == str(job_id)))
            if row is None:
                return None
            job = self._to_job(row)
            for key, value in changes.items():
                setattr(job, key, value)
            self._write_job(row, job, created=False)
            session.flush()
            return self._to_job(row)

    def due_jobs(self, now: datetime) -> list[AutomationJob]:
        current = self._as_utc(now)
        due = [
            job
            for job in self.list_jobs()
            if job.state is AutomationJobState.ACTIVE
            and job.next_run_at is not None
            and self._as_utc(job.next_run_at) <= current
        ]
        due.sort(key=lambda item: (-item.priority, item.next_run_at or current, item.job_id))
        return due

    def append_history(self, record: AutomationRunRecord) -> None:
        with session_scope() as session:
            session.add(
                AutomationRunRow(
                    run_id=record.run_id,
                    job_id=record.job_id,
                    status=record.status.value,
                    trigger=record.trigger.value,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    queue=record.queue_type.value,
                    pipeline_job_id=record.pipeline_job_id,
                    error_message=record.error_message,
                    attempt=record.attempt,
                )
            )

    def list_history(self) -> list[AutomationRunRecord]:
        with session_scope() as session:
            rows = list(session.scalars(select(AutomationRunRow).order_by(AutomationRunRow.started_at, AutomationRunRow.run_id)))
            return [self._to_run_record(row) for row in rows]

    def count_history(self) -> int:
        return len(self.list_history())

    def has_success(self, job_id: str) -> bool:
        with session_scope() as session:
            row = session.scalar(
                select(AutomationRunRow.id)
                .where(
                    AutomationRunRow.job_id == str(job_id),
                    AutomationRunRow.status == AutomationRunStatus.QUEUED.value,
                )
                .limit(1)
            )
            return row is not None

    _MUTABLE_FIELDS = {
        "name",
        "action",
        "queue_type",
        "priority",
        "schedule_type",
        "trigger_type",
        "run_at",
        "interval_seconds",
        "cron_expression",
        "dependencies",
        "condition",
        "payload",
        "retry_policy",
        "next_run_at",
        "state",
        "retries",
        "failures",
        "successes",
        "last_error",
        "last_run_at",
    }

    @classmethod
    def _write_job(cls, row: AutomationJobRow, job: AutomationJob, *, created: bool) -> None:
        row.name = job.name
        row.action = job.action
        row.queue = job.queue_type.value
        row.priority = job.priority
        row.schedule_type = job.schedule_type.value
        row.trigger_type = job.trigger_type.value
        row.run_at = job.run_at
        row.interval_seconds = job.interval_seconds
        row.cron_expression = job.cron_expression
        row.dependencies = sorted(job.dependencies)
        row.condition = None if job.condition is None else {"key": job.condition.key, "equals": job.condition.equals}
        row.payload = dict(job.payload)
        row.retry_policy = {
            "max_retries": job.retry_policy.max_retries,
            "backoff_seconds": job.retry_policy.backoff_seconds,
            "exponential_backoff": job.retry_policy.exponential_backoff,
        }
        row.next_run_at = job.next_run_at
        row.state = job.state.value
        row.retries = job.retries
        row.failures = job.failures
        row.successes = job.successes
        row.last_error = job.last_error
        row.last_run_at = job.last_run_at
        if created:
            row.created_at = job.created_at
        row.updated_at = datetime.now(timezone.utc)

    @classmethod
    def _to_job(cls, row: AutomationJobRow) -> AutomationJob:
        condition_payload = row.condition or {}
        retry_policy_payload = row.retry_policy or {}
        return AutomationJob(
            job_id=row.job_id,
            name=row.name,
            action=row.action,
            queue_type=QueueType(row.queue),
            priority=row.priority,
            schedule_type=AutomationScheduleType(row.schedule_type),
            trigger_type=AutomationTriggerType(row.trigger_type),
            run_at=cls._as_utc_or_none(row.run_at),
            interval_seconds=row.interval_seconds,
            cron_expression=row.cron_expression,
            dependencies=set(row.dependencies or []),
            condition=(
                None
                if not condition_payload
                else AutomationCondition(
                    key=str(condition_payload.get("key", "")),
                    equals=str(condition_payload.get("equals", "")),
                )
            ),
            payload=dict(row.payload or {}),
            retry_policy=AutomationRetryPolicy(
                max_retries=int(retry_policy_payload.get("max_retries", 0)),
                backoff_seconds=int(retry_policy_payload.get("backoff_seconds", 30)),
                exponential_backoff=bool(retry_policy_payload.get("exponential_backoff", True)),
            ),
            next_run_at=cls._as_utc_or_none(row.next_run_at),
            state=AutomationJobState(row.state),
            retries=row.retries,
            failures=row.failures,
            successes=row.successes,
            last_error=row.last_error,
            last_run_at=cls._as_utc_or_none(row.last_run_at),
            created_at=cls._as_utc(row.created_at),
            updated_at=cls._as_utc(row.updated_at),
        )

    @classmethod
    def _to_run_record(cls, row: AutomationRunRow) -> AutomationRunRecord:
        return AutomationRunRecord(
            run_id=row.run_id,
            job_id=row.job_id,
            status=AutomationRunStatus(row.status),
            trigger=AutomationTriggerType(row.trigger),
            started_at=cls._as_utc(row.started_at),
            finished_at=cls._as_utc(row.finished_at),
            queue_type=QueueType(row.queue),
            pipeline_job_id=row.pipeline_job_id,
            error_message=row.error_message,
            attempt=row.attempt,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @classmethod
    def _as_utc_or_none(cls, value: datetime | None) -> datetime | None:
        return None if value is None else cls._as_utc(value)
