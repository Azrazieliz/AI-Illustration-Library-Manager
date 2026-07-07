from __future__ import annotations

from threading import Event, Thread

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.search_advanced.search_models import AdvancedSearchCheckpoint, AdvancedSearchOperationResult
from engine.search_advanced.search_service import AdvancedSearchService


class AdvancedSearchWorker:
    """Background worker that consumes advanced search jobs from SEARCH queue."""

    _POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: AdvancedSearchService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or AdvancedSearchService(queue_manager=self.queue_manager)
        self._checkpoint = AdvancedSearchCheckpoint()
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._cancelled_job_ids: set[str] = set()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="advanced-search-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def cancel(self, job_id: str | None = None) -> None:
        if job_id is None:
            self._stop_event.set()
            return
        self._cancelled_job_ids.add(str(job_id))
        self._checkpoint.cancel(str(job_id))
        self.service.engine.statistics.increment_cancelled()

    def resume(self, job_id: str | None = None) -> None:
        if job_id is None:
            self._stop_event.clear()
            return
        self._cancelled_job_ids.discard(str(job_id))
        self._checkpoint.resume(str(job_id))
        self.service.engine.statistics.increment_resumed()

    def is_cancelled(self, job_id: str) -> bool:
        return str(job_id) in self._cancelled_job_ids or self._checkpoint.is_cancelled(job_id)

    def process_jobs(self, jobs: list[PipelineJob]) -> list[AdvancedSearchOperationResult]:
        results: list[AdvancedSearchOperationResult] = []
        for job in jobs:
            if self._should_skip(job):
                continue
            result = self.service.process_advanced_search_job(job, checkpoint=self._checkpoint)
            if result is not None:
                results.append(result)
        return results

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job: PipelineJob | None = self.queue_manager.dequeue(QueueType.SEARCH)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            if self._should_skip(job):
                continue
            if (job.metadata or {}).get("stage") != "advanced_search":
                continue
            self.service.process_advanced_search_job(job, checkpoint=self._checkpoint)

    def _should_skip(self, job: PipelineJob) -> bool:
        job_id = str(job.id)
        if self._checkpoint.is_processed_job(job_id):
            return True
        if job_id in self._cancelled_job_ids or self._checkpoint.is_cancelled(job_id):
            return True
        return False
