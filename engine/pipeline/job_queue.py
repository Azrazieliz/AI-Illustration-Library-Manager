from __future__ import annotations

from queue import Empty, PriorityQueue, Queue
from threading import Lock
from typing import Callable, Generic, TypeVar

from engine.logging import get_logger
from engine.pipeline.pipeline_events import JobFailed, JobFinished, JobQueued, JobStarted, QueuePaused, QueueResumed
from engine.pipeline.pipeline_models import PipelineJob, PipelineJobStatus, QueueType

T = TypeVar("T", bound=PipelineJob)


class BaseQueue(Generic[T]):
    """A thread-safe queue for pipeline jobs."""

    def __init__(self, queue_type: QueueType, *, callback: Callable[[object], None] | None = None) -> None:
        self.queue_type = queue_type
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self._queue: PriorityQueue[tuple[int, int, T]] = PriorityQueue()
        self._lock = Lock()
        self._paused = False
        self._stats: dict[str, int] = {"queued": 0, "dequeued": 0, "completed": 0, "failed": 0, "cancelled": 0}

    def enqueue(self, job: T) -> T:
        with self._lock:
            if self._paused:
                raise RuntimeError(f"Queue {self.queue_type.value} is paused")
            job.status = PipelineJobStatus.PENDING
            self._queue.put((-job.priority, self._stats["queued"], job))
            self._stats["queued"] += 1
        self._emit(JobQueued(job=job, queue_type=self.queue_type))
        return job

    def dequeue(self) -> T | None:
        with self._lock:
            if self._paused:
                return None
            try:
                _, _, job = self._queue.get_nowait()
            except Empty:
                return None
            job.status = PipelineJobStatus.RUNNING
            self._stats["dequeued"] += 1
            return job

    def peek(self) -> T | None:
        with self._lock:
            if self._queue.empty():
                return None
            _, _, job = self._queue.queue[0]
            return job

    def cancel(self, job: T) -> None:
        with self._lock:
            job.status = PipelineJobStatus.CANCELLED
            self._stats["cancelled"] += 1

    def pending_count(self) -> int:
        with self._lock:
            return self._queue.qsize()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
        self._emit(QueuePaused(queue_type=self.queue_type))

    def resume(self) -> None:
        with self._lock:
            self._paused = False
        self._emit(QueueResumed(queue_type=self.queue_type))

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def mark_started(self, job: T) -> None:
        job.status = PipelineJobStatus.RUNNING
        self._emit(JobStarted(job=job, queue_type=self.queue_type))

    def mark_completed(self, job: T) -> None:
        job.status = PipelineJobStatus.COMPLETED
        self._stats["completed"] += 1
        self._emit(JobFinished(job=job, queue_type=self.queue_type))

    def mark_failed(self, job: T, error_message: str) -> None:
        job.status = PipelineJobStatus.FAILED
        job.error_message = error_message
        self._stats["failed"] += 1
        self._emit(JobFailed(job=job, queue_type=self.queue_type, error_message=error_message))

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)


class DiscoveryQueue(BaseQueue[PipelineJob]):
    """Queue for discovery jobs emitted by the scanner."""

    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.DISCOVERY, callback=callback)


class IndexQueue(BaseQueue[PipelineJob]):
    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.INDEX, callback=callback)


class HashQueue(BaseQueue[PipelineJob]):
    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.HASH, callback=callback)


class ThumbnailQueue(BaseQueue[PipelineJob]):
    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.THUMBNAIL, callback=callback)


class DuplicateQueue(BaseQueue[PipelineJob]):
    """Queue for duplicate-detection jobs published by the hash engine."""

    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.DUPLICATE, callback=callback)


class EmbeddingQueue(BaseQueue[PipelineJob]):
    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.EMBEDDING, callback=callback)


class RecognitionQueue(BaseQueue[PipelineJob]):
    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.RECOGNITION, callback=callback)


class ReviewQueue(BaseQueue[PipelineJob]):
    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.REVIEW, callback=callback)


class TransactionQueue(BaseQueue[PipelineJob]):
    def __init__(self, *, callback: Callable[[object], None] | None = None) -> None:
        super().__init__(QueueType.TRANSACTION, callback=callback)
