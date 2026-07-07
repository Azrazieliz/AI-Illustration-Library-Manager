from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from engine.pipeline.pipeline_models import QueueType


class AutomationScheduleType(str, Enum):
    ONE_SHOT = "one_shot"
    RECURRING = "recurring"
    CRON = "cron"


class AutomationTriggerType(str, Enum):
    SCHEDULED = "scheduled"
    EVENT = "event"
    PIPELINE = "pipeline"
    MANUAL = "manual"


class AutomationJobState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class AutomationRunStatus(str, Enum):
    QUEUED = "queued"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class AutomationRetryPolicy:
    max_retries: int = 0
    backoff_seconds: int = 30
    exponential_backoff: bool = True


@dataclass(slots=True)
class AutomationCondition:
    key: str
    equals: str


@dataclass(slots=True)
class AutomationJob:
    job_id: str
    name: str
    action: str
    queue_type: QueueType = QueueType.SEARCH
    priority: int = 0
    schedule_type: AutomationScheduleType = AutomationScheduleType.ONE_SHOT
    trigger_type: AutomationTriggerType = AutomationTriggerType.SCHEDULED
    run_at: datetime | None = None
    interval_seconds: int | None = None
    cron_expression: str | None = None
    dependencies: set[str] = field(default_factory=set)
    condition: AutomationCondition | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    retry_policy: AutomationRetryPolicy = field(default_factory=AutomationRetryPolicy)
    next_run_at: datetime | None = None
    state: AutomationJobState = AutomationJobState.ACTIVE
    retries: int = 0
    failures: int = 0
    successes: int = 0
    last_error: str | None = None
    last_run_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class AutomationRunRecord:
    run_id: str
    job_id: str
    status: AutomationRunStatus
    trigger: AutomationTriggerType
    started_at: datetime
    finished_at: datetime
    queue_type: QueueType
    pipeline_job_id: str | None = None
    error_message: str | None = None
    attempt: int = 0


@dataclass(slots=True)
class AutomationCheckpoint:
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


@dataclass(slots=True)
class AutomationOperationResult:
    action: str
    success: bool
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AutomationProgress:
    total_jobs: int
    active_jobs: int
    paused_jobs: int
    cancelled_jobs: int
    completed_jobs: int
    failed_jobs: int
