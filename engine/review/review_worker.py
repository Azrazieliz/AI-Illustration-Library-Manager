from __future__ import annotations

from threading import Event, Thread

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.review.review_service import ReviewService


class ReviewWorker:
    """Background worker that consumes REVIEW queue jobs."""

    _POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: ReviewService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or ReviewService(queue_manager=self.queue_manager)
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="review-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_jobs(self, jobs: list[PipelineJob]) -> None:
        self.service.process_review_jobs(jobs)

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job = self.queue_manager.dequeue(QueueType.REVIEW)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            self.service.process_review_job(job)
