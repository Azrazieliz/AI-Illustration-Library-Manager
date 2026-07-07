from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from typing import Iterable

from engine.hashing.hash_engine import HashEngine
from engine.hashing.hash_models import HashCheckpoint
from engine.hashing.hash_service import HashService
from engine.pipeline import PipelineJob, QueueManager, QueueType


class HashWorker:
    """Background worker that drains the HASH queue and publishes DUPLICATE jobs.

    The worker runs on a dedicated daemon thread.  It polls the HASH queue and
    processes each job through :class:`HashService`.  A :class:`HashCheckpoint`
    is maintained across the entire worker lifetime to prevent re-hashing the
    same content after a crash-and-restart cycle.
    """

    _POLL_INTERVAL: float = 0.05  # seconds between empty-queue polls

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        hash_service: HashService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.hash_service = hash_service or HashService(queue_manager=self.queue_manager)
        self._checkpoint = HashCheckpoint()
        self._thread: Thread | None = None
        self._stop_event = Event()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the background worker thread."""
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="hash-worker")
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker to stop and wait for the thread to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_paths(self, paths: Iterable[Path | str]) -> None:
        """Enqueue *paths* as HASH jobs and process them synchronously.

        Useful for direct integration tests and one-shot batch runs without
        starting the background thread.
        """
        jobs: list[PipelineJob] = []
        for path in paths:
            job = PipelineJob(source_path=str(Path(path).resolve()), queue_type=QueueType.HASH)
            self.queue_manager.enqueue(QueueType.HASH, job)
            jobs.append(job)
        for job in jobs:
            self.hash_service.process_hash_job(job, checkpoint=self._checkpoint)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job: PipelineJob | None = self.queue_manager.dequeue(QueueType.HASH)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            self.hash_service.process_hash_job(job, checkpoint=self._checkpoint)
