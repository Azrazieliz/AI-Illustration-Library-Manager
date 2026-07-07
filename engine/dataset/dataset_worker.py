from __future__ import annotations

from threading import Event, Thread

from engine.dataset.dataset_models import DatasetCheckpoint
from engine.dataset.dataset_service import DatasetService
from engine.pipeline import PipelineJob, QueueManager, QueueType


class DatasetWorker:
    """Background worker that consumes stage-marked SEARCH jobs for dataset build."""

    _POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: DatasetService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or DatasetService(queue_manager=self.queue_manager)
        self._checkpoint = DatasetCheckpoint()
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="dataset-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_jobs(self, jobs: list[PipelineJob], *, rebuild: bool = False) -> None:
        self.service.process_dataset_jobs(jobs, checkpoint=self._checkpoint, rebuild=rebuild)

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job: PipelineJob | None = self.queue_manager.dequeue(QueueType.SEARCH)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            stage = (job.metadata or {}).get("stage")
            if stage != "dataset":
                continue
            rebuild = bool((job.metadata or {}).get("rebuild", False))
            self.service.process_dataset_job(job, checkpoint=self._checkpoint, rebuild=rebuild)
