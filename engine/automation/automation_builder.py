from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from engine.automation.automation_exceptions import (
    AutomationDependencyError,
    AutomationScheduleError,
    AutomationValidationError,
)
from engine.automation.automation_models import (
    AutomationCondition,
    AutomationJob,
    AutomationRetryPolicy,
    AutomationScheduleType,
    AutomationTriggerType,
)
from engine.pipeline.pipeline_models import QueueType


class AutomationBuilder:
    """Builds validated automation jobs and schedule plans."""

    def build_job(
        self,
        *,
        job_id: str,
        name: str,
        action: str,
        queue_type: QueueType = QueueType.SEARCH,
        priority: int = 0,
        schedule_type: AutomationScheduleType = AutomationScheduleType.ONE_SHOT,
        trigger_type: AutomationTriggerType = AutomationTriggerType.SCHEDULED,
        run_at: datetime | None = None,
        interval_seconds: int | None = None,
        cron_expression: str | None = None,
        dependencies: set[str] | None = None,
        condition: AutomationCondition | None = None,
        payload: dict[str, Any] | None = None,
        retry_policy: AutomationRetryPolicy | None = None,
    ) -> AutomationJob:
        if not str(job_id).strip() or not str(name).strip() or not str(action).strip():
            raise AutomationValidationError("job_id, name, and action are required")

        if schedule_type is AutomationScheduleType.ONE_SHOT and run_at is None:
            raise AutomationValidationError("one-shot jobs require run_at")

        if schedule_type is AutomationScheduleType.RECURRING and (interval_seconds is None or interval_seconds <= 0):
            raise AutomationValidationError("recurring jobs require interval_seconds > 0")

        if schedule_type is AutomationScheduleType.CRON and not str(cron_expression or "").strip():
            raise AutomationValidationError("cron jobs require cron_expression")

        now = datetime.now(timezone.utc)
        next_run_at = self.initial_next_run(
            schedule_type=schedule_type,
            run_at=run_at,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            now=now,
        )

        return AutomationJob(
            job_id=str(job_id).strip(),
            name=str(name).strip(),
            action=str(action).strip(),
            queue_type=queue_type,
            priority=int(priority),
            schedule_type=schedule_type,
            trigger_type=trigger_type,
            run_at=run_at,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            dependencies=set(dependencies or set()),
            condition=condition,
            payload=dict(payload or {}),
            retry_policy=retry_policy or AutomationRetryPolicy(),
            next_run_at=next_run_at,
        )

    def build_delayed_job(
        self,
        *,
        job_id: str,
        name: str,
        action: str,
        delay_seconds: int,
        queue_type: QueueType = QueueType.SEARCH,
        priority: int = 0,
        payload: dict[str, Any] | None = None,
        retry_policy: AutomationRetryPolicy | None = None,
    ) -> AutomationJob:
        run_at = datetime.now(timezone.utc) + timedelta(seconds=max(0, int(delay_seconds)))
        return self.build_job(
            job_id=job_id,
            name=name,
            action=action,
            queue_type=queue_type,
            priority=priority,
            schedule_type=AutomationScheduleType.ONE_SHOT,
            trigger_type=AutomationTriggerType.SCHEDULED,
            run_at=run_at,
            payload=payload,
            retry_policy=retry_policy,
        )

    def initial_next_run(
        self,
        *,
        schedule_type: AutomationScheduleType,
        run_at: datetime | None,
        interval_seconds: int | None,
        cron_expression: str | None,
        now: datetime,
    ) -> datetime | None:
        if schedule_type is AutomationScheduleType.ONE_SHOT:
            return run_at
        if schedule_type is AutomationScheduleType.RECURRING:
            return now + timedelta(seconds=max(1, int(interval_seconds or 1)))
        if schedule_type is AutomationScheduleType.CRON:
            return self.next_cron_after(now, str(cron_expression))
        raise AutomationScheduleError(f"Unsupported schedule type: {schedule_type}")

    def next_run_after_success(self, job: AutomationJob, now: datetime) -> datetime | None:
        if job.schedule_type is AutomationScheduleType.ONE_SHOT:
            return None
        if job.schedule_type is AutomationScheduleType.RECURRING:
            return now + timedelta(seconds=max(1, int(job.interval_seconds or 1)))
        if job.schedule_type is AutomationScheduleType.CRON:
            return self.next_cron_after(now, str(job.cron_expression or "* * * * *"))
        return None

    def next_run_after_failure(self, job: AutomationJob, now: datetime) -> datetime:
        retry_index = max(1, job.retries)
        base = max(1, int(job.retry_policy.backoff_seconds))
        if job.retry_policy.exponential_backoff:
            delay = base * (2 ** (retry_index - 1))
        else:
            delay = base
        return now + timedelta(seconds=delay)

    def resolve_dependency_order(self, jobs: list[AutomationJob]) -> list[AutomationJob]:
        by_id = {job.job_id: job for job in jobs}
        indegree = {job.job_id: 0 for job in jobs}
        edges: dict[str, set[str]] = {job.job_id: set() for job in jobs}

        for job in jobs:
            for dep in sorted(job.dependencies):
                if dep not in by_id:
                    continue
                if job.job_id not in edges[dep]:
                    edges[dep].add(job.job_id)
                    indegree[job.job_id] += 1

        ready = sorted([job_id for job_id, degree in indegree.items() if degree == 0])
        ordered: list[str] = []

        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for neighbor in sorted(edges[current]):
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    ready.append(neighbor)
                    ready.sort()

        if len(ordered) != len(jobs):
            raise AutomationDependencyError("Dependency cycle detected")

        return [by_id[job_id] for job_id in ordered]

    def condition_matches(self, condition: AutomationCondition | None, context: dict[str, Any]) -> bool:
        if condition is None:
            return True
        value = context.get(condition.key)
        return str(value) == str(condition.equals)

    def normalize_job(self, job: AutomationJob) -> AutomationJob:
        normalized = replace(job)
        if normalized.next_run_at is None and normalized.schedule_type is AutomationScheduleType.ONE_SHOT:
            normalized.next_run_at = normalized.run_at
        return normalized

    def next_cron_after(self, now: datetime, expression: str) -> datetime:
        fields = str(expression).split()
        if len(fields) != 5:
            raise AutomationScheduleError("Cron expression must have 5 fields: minute hour day month weekday")
        minute_field, hour_field, day_field, month_field, weekday_field = fields

        candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = candidate + timedelta(days=370)
        while candidate <= limit:
            if (
                self._cron_field_match(candidate.minute, minute_field, 0, 59)
                and self._cron_field_match(candidate.hour, hour_field, 0, 23)
                and self._cron_field_match(candidate.day, day_field, 1, 31)
                and self._cron_field_match(candidate.month, month_field, 1, 12)
                and self._cron_field_match(candidate.weekday(), weekday_field, 0, 6)
            ):
                return candidate
            candidate += timedelta(minutes=1)
        raise AutomationScheduleError(f"Could not resolve next cron run for {expression}")

    def _cron_field_match(self, value: int, field: str, minimum: int, maximum: int) -> bool:
        token = field.strip()
        if token == "*":
            return True

        allowed: set[int] = set()
        for part in token.split(","):
            part = part.strip()
            if not part:
                continue
            if part.startswith("*/"):
                step = int(part[2:])
                allowed.update(range(minimum, maximum + 1, max(1, step)))
                continue
            if "-" in part:
                start_raw, end_raw = part.split("-", maxsplit=1)
                start = int(start_raw)
                end = int(end_raw)
                allowed.update(range(max(minimum, start), min(maximum, end) + 1))
                continue
            allowed.add(int(part))

        return value in allowed
