from __future__ import annotations

from threading import Event, Lock, Thread
from typing import Callable

from engine.logging import get_logger
from engine.pipeline.job_queue import BaseQueue
from engine.pipeline.pipeline_events import JobFailed, JobFinished, JobStarted
from engine.pipeline.pipeline_models import PipelineJob, PipelineJobStatus, QueueType


class PipelineWorker:
    """Thread-safe worker that consumes jobs from a single queue."""

    def __init__(self, queue: BaseQueue[PipelineJob], callback: Callable[[object], None] | None = None) -> None:
        self.queue = queue
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._pause_event = Event()
        self._lock = Lock()
        self._status = PipelineJobStatus.PENDING

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._pause_event.clear()
            self._thread = Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            self._pause_event.clear()

    def pause(self) -> None:
        with self._lock:
            self._pause_event.set()

    def resume(self) -> None:
        with self._lock:
            self._pause_event.clear()

    def consume(self) -> PipelineJob | None:
        return self.queue.dequeue()

    def process(self, job: PipelineJob) -> PipelineJob:
        self.queue.mark_started(job)
        self.queue.mark_completed(job)
        return job

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                continue
            job = self.consume()
            if job is None:
                continue
            self.process(job)
