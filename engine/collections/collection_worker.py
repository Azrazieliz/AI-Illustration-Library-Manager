from __future__ import annotations

from threading import Event, Thread

from engine.collections.collection_models import CollectionCheckpoint
from engine.collections.collection_service import CollectionService
from engine.pipeline import PipelineJob, QueueManager, QueueType


class CollectionWorker:
    """Background worker that consumes stage-marked SEARCH jobs for collections."""

    _POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: CollectionService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or CollectionService(queue_manager=self.queue_manager)
        self._checkpoint = CollectionCheckpoint()
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="collection-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_jobs(self, jobs: list[PipelineJob]) -> None:
        self.service.process_collection_jobs(jobs, checkpoint=self._checkpoint)

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job: PipelineJob | None = self.queue_manager.dequeue(QueueType.SEARCH)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            stage = (job.metadata or {}).get("stage")
            if stage != "collection":
                continue
            self.service.process_collection_job(job, checkpoint=self._checkpoint)
