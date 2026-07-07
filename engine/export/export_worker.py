from __future__ import annotations

from threading import Event, Thread

from engine.export.export_models import ExportCheckpoint
from engine.export.export_service import ExportService
from engine.pipeline import PipelineJob, QueueManager, QueueType


class ExportWorker:
    """Background worker that consumes stage-marked SEARCH jobs for export."""

    _POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: ExportService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or ExportService(queue_manager=self.queue_manager)
        self._checkpoint = ExportCheckpoint()
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="export-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_jobs(self, jobs: list[PipelineJob]) -> None:
        self.service.process_export_jobs(jobs, checkpoint=self._checkpoint)

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job: PipelineJob | None = self.queue_manager.dequeue(QueueType.SEARCH)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            stage = (job.metadata or {}).get("stage")
            if stage != "export":
                continue
            self.service.process_export_job(job, checkpoint=self._checkpoint)
