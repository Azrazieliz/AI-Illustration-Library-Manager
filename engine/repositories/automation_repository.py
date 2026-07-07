from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from engine.automation.automation_models import AutomationJob, AutomationJobState, AutomationRunRecord, AutomationRunStatus


class AutomationRepository:
    """Thread-safe in-memory store for automation schedules and execution history."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, AutomationJob] = {}
        self._history: list[AutomationRunRecord] = []

    def upsert_job(self, job: AutomationJob) -> AutomationJob:
        with self._lock:
            stored = deepcopy(job)
            stored.updated_at = datetime.now(timezone.utc)
            self._jobs[stored.job_id] = stored
            return deepcopy(stored)

    def get_job(self, job_id: str) -> AutomationJob | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            return deepcopy(job) if job is not None else None

    def list_jobs(self) -> list[AutomationJob]:
        with self._lock:
            items = [deepcopy(item) for item in self._jobs.values()]
        items.sort(key=lambda item: item.job_id)
        return items

    def remove_job(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(str(job_id), None) is not None

    def set_job_state(self, job_id: str, state: AutomationJobState) -> AutomationJob | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                return None
            job.state = state
            job.updated_at = datetime.now(timezone.utc)
            return deepcopy(job)

    def update_job_fields(self, job_id: str, **changes: Any) -> AutomationJob | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                return None
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = datetime.now(timezone.utc)
            return deepcopy(job)

    def due_jobs(self, now: datetime) -> list[AutomationJob]:
        with self._lock:
            due = [
                deepcopy(job)
                for job in self._jobs.values()
                if job.state is AutomationJobState.ACTIVE and job.next_run_at is not None and job.next_run_at <= now
            ]
        due.sort(key=lambda item: (-item.priority, item.next_run_at or now, item.job_id))
        return due

    def append_history(self, record: AutomationRunRecord) -> None:
        with self._lock:
            self._history.append(deepcopy(record))

    def list_history(self) -> list[AutomationRunRecord]:
        with self._lock:
            records = [deepcopy(item) for item in self._history]
        records.sort(key=lambda item: (item.started_at, item.run_id))
        return records

    def count_history(self) -> int:
        with self._lock:
            return len(self._history)

    def has_success(self, job_id: str) -> bool:
        with self._lock:
            return any(item.job_id == job_id and item.status is AutomationRunStatus.QUEUED for item in self._history)
