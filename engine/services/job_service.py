from __future__ import annotations

from engine.database.models.job import Job
from engine.repositories.job_repository import JobRepository
from engine.services.base_service import BaseService


class JobService(BaseService[Job]):
    """Service layer for job entities."""

    def __init__(self, repository: JobRepository | None = None) -> None:
        super().__init__(repository or JobRepository())
        self.repository = repository or JobRepository()

    def create_job(self, *, job_type: str, priority: int = 0) -> Job:
        return self.repository.create_job(job_type=job_type, priority=priority)

    def start_job(self, job: Job) -> Job:
        return self.repository.start_job(job)

    def finish_job(self, job: Job) -> Job:
        return self.repository.finish_job(job)

    def cancel_job(self, job: Job) -> Job:
        return self.repository.cancel_job(job)

    def update_progress(self, job: Job, progress: int) -> Job:
        return self.repository.update_progress(job, progress)

    def list_running_jobs(self) -> list[Job]:
        return self.repository.list_running_jobs()
