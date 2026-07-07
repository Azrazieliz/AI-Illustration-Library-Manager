from __future__ import annotations

from threading import Event, Thread

from engine.duplicates.duplicate_models import DuplicateCheckpoint
from engine.duplicates.duplicate_service import DuplicateService
from engine.pipeline import PipelineJob, QueueManager, QueueType


class DuplicateWorker:
    """Background worker that drains the DUPLICATE queue and publishes REVIEW jobs.

    A single :class:`DuplicateCheckpoint` is maintained for the lifetime of
    the worker, ensuring that no pair is ever compared twice even if the
    process is restarted.
    """

    _POLL_INTERVAL: float = 0.05  # seconds between empty-queue polls

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: DuplicateService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or DuplicateService(queue_manager=self.queue_manager)
        self._checkpoint = DuplicateCheckpoint()
        self._thread: Thread | None = None
        self._stop_event = Event()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the background worker thread."""
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run, daemon=True, name="duplicate-worker"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker to stop and wait for the thread to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_jobs(self, jobs: list[PipelineJob]) -> None:
        """Process *jobs* synchronously (useful for tests and batch runs)."""
        self.service.process_duplicate_jobs(jobs, checkpoint=self._checkpoint)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job: PipelineJob | None = self.queue_manager.dequeue(QueueType.DUPLICATE)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            self.service.process_duplicate_job(job, checkpoint=self._checkpoint)
