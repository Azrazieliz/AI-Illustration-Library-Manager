from __future__ import annotations

from threading import Event, Thread

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.rename.rename_models import RenameRule
from engine.rename.rename_service import RenameService


class RenameWorker:
    """Background worker that consumes stage-marked SEARCH jobs for rename."""

    _POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: RenameService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or RenameService(queue_manager=self.queue_manager)
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="rename-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        rule: RenameRule | None = None,
        dry_run: bool = False,
    ) -> None:
        self.service.process_rename_jobs(jobs, rule=rule, dry_run=dry_run)

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job = self.queue_manager.dequeue(QueueType.SEARCH)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue

            stage = (job.metadata or {}).get("stage")
            if stage != "rename":
                continue

            dry_run = bool((job.metadata or {}).get("dry_run", False))
            self.service.process_rename_job(job, dry_run=dry_run)
