from __future__ import annotations

from threading import Event, Thread

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.search.search_models import SearchCheckpoint
from engine.search.search_service import SearchService


class SearchWorker:
    """Background worker that drains the SEARCH queue."""

    _POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: SearchService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or SearchService(queue_manager=self.queue_manager)
        self._checkpoint = SearchCheckpoint()
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self) -> None:
        """Start search worker thread."""
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="search-worker")
        self._thread.start()

    def stop(self) -> None:
        """Stop worker and wait for shutdown."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_jobs(self, jobs: list[PipelineJob]) -> None:
        """Process jobs synchronously (used by tests)."""
        self.service.process_search_jobs(jobs, checkpoint=self._checkpoint)

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job: PipelineJob | None = self.queue_manager.dequeue(QueueType.SEARCH)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            self.service.process_search_job(job, checkpoint=self._checkpoint)
