from __future__ import annotations

from datetime import datetime, timezone

from engine.database.models.job import Job
from engine.services.base_service import BaseService


class JobService(BaseService[Job]):
    """Service layer for job entities."""

    def create_job(self, *, job_type: str, priority: int = 0) -> Job:
        job = Job(type=job_type, priority=priority, status="pending")
        self.add(job)
        self.commit()
        return job

    def start_job(self, job: Job) -> Job:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        self.commit()
        return job

    def finish_job(self, job: Job) -> Job:
        job.status = "finished"
        job.finished_at = datetime.now(timezone.utc)
        self.commit()
        return job

    def cancel_job(self, job: Job) -> Job:
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        self.commit()
        return job

    def update_progress(self, job: Job, progress: int) -> Job:
        job.progress = progress
        self.commit()
        return job

    def list_running_jobs(self) -> list[Job]:
        return list(self.session.query(Job).filter(Job.status == "running").all())
