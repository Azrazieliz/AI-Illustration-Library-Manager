from __future__ import annotations

from collections import defaultdict
from typing import Callable

from engine.logging import get_logger
from engine.pipeline.job_queue import (
    DiscoveryQueue,
    EmbeddingQueue,
    HashQueue,
    IndexQueue,
    RecognitionQueue,
    ReviewQueue,
    ThumbnailQueue,
    TransactionQueue,
)
from engine.pipeline.pipeline_models import PipelineJob, PipelineJobStatus, QueueType


class QueueManager:
    """Central registry for the local queue-driven processing pipeline."""

    def __init__(self, callback: Callable[[object], None] | None = None) -> None:
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self._queues: dict[QueueType, object] = {}
        self._register_default_queues()

    def _register_default_queues(self) -> None:
        self.register(DiscoveryQueue(callback=self.callback))
        self.register(IndexQueue(callback=self.callback))
        self.register(HashQueue(callback=self.callback))
        self.register(ThumbnailQueue(callback=self.callback))
        self.register(EmbeddingQueue(callback=self.callback))
        self.register(RecognitionQueue(callback=self.callback))
        self.register(ReviewQueue(callback=self.callback))
        self.register(TransactionQueue(callback=self.callback))

    def register(self, queue: object) -> None:
        queue_type = getattr(queue, "queue_type")
        self._queues[queue_type] = queue

    def enqueue(self, queue_type: QueueType, job: PipelineJob) -> PipelineJob:
        queue = self._queues[queue_type]
        return queue.enqueue(job)

    def dequeue(self, queue_type: QueueType) -> PipelineJob | None:
        queue = self._queues[queue_type]
        return queue.dequeue()

    def peek(self, queue_type: QueueType) -> PipelineJob | None:
        queue = self._queues[queue_type]
        return queue.peek()

    def cancel(self, queue_type: QueueType, job: PipelineJob) -> None:
        queue = self._queues[queue_type]
        queue.cancel(job)

    def retry(self, queue_type: QueueType, job: PipelineJob) -> PipelineJob:
        job.retry_count += 1
        job.status = PipelineJobStatus.PENDING
        return self.enqueue(queue_type, job)

    def pause_queue(self, queue_type: QueueType) -> None:
        self._queues[queue_type].pause()

    def resume_queue(self, queue_type: QueueType) -> None:
        self._queues[queue_type].resume()

    def statistics(self) -> dict[QueueType, dict[str, int]]:
        return {queue_type: queue.stats() for queue_type, queue in self._queues.items()}

    def queues(self) -> tuple[QueueType, ...]:
        return tuple(self._queues.keys())
