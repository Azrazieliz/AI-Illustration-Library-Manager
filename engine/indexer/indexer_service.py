from __future__ import annotations

from pathlib import Path
from typing import Iterable

from engine.indexer.indexer import IncrementalIndexer
from engine.indexer.indexer_events import FileDeleted, FileIndexed, FileModified, IndexCompleted, IndexStarted
from engine.indexer.indexer_models import IndexDecision, IndexerCheckpoint
from engine.pipeline import PipelineJob, QueueManager, QueueType


class IndexerService:
    """Service façade for the incremental indexer pipeline integration."""

    def __init__(self, *, queue_manager: QueueManager | None = None, indexer: IncrementalIndexer | None = None) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.indexer = indexer or IncrementalIndexer(callback=self._handle_event)

    def index_paths(self, paths: Iterable[Path | str], *, checkpoint: IndexerCheckpoint | None = None) -> list[PipelineJob]:
        jobs: list[PipelineJob] = []
        for record in self.indexer.index_paths(list(paths), checkpoint=checkpoint):
            if record.decision in {IndexDecision.NEW, IndexDecision.MODIFIED}:
                job = PipelineJob(source_path=record.source_path, queue_type=QueueType.HASH)
                self.queue_manager.enqueue(QueueType.HASH, job)
                jobs.append(job)
        return jobs

    def process_discovery_job(self, job: PipelineJob) -> PipelineJob | None:
        if not job.source_path:
            return None
        jobs = self.index_paths([job.source_path])
        return jobs[0] if jobs else None

    def _handle_event(self, event: object) -> None:
        return None
