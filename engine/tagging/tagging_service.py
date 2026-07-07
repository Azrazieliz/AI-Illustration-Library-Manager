from __future__ import annotations

from pathlib import Path

from engine.pipeline import PipelineJob, QueueManager
from engine.tagging.tagging_engine import TaggingEngine
from engine.tagging.tagging_models import TaggingCheckpoint, TaggingResult


class TaggingService:
    """Service facade connecting automatic tagging engine to pipeline jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: TaggingEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or TaggingEngine(callback=self._handle_event)

    def process_tagging_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: TaggingCheckpoint | None = None,
    ) -> TaggingResult | None:
        if not job.source_path:
            return None

        stage = (job.metadata or {}).get("stage")
        if stage != "tagging":
            return None

        return self.engine.process_path(
            Path(job.source_path),
            checkpoint=checkpoint,
            metadata=job.metadata,
        )

    def process_tagging_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: TaggingCheckpoint | None = None,
    ) -> list[TaggingResult]:
        results: list[TaggingResult] = []
        for job in jobs:
            result = self.process_tagging_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    def _handle_event(self, event: object) -> None:
        return None
