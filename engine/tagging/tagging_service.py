from __future__ import annotations

from pathlib import Path

from engine.pipeline import PipelineJob, QueueManager, QueueType
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

        result = self.engine.process_path(
            Path(job.source_path),
            checkpoint=checkpoint,
            metadata=job.metadata,
        )
        if result is not None:
            self._publish_dataset_job(job, result)
        return result

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

    def _publish_dataset_job(self, original_job: PipelineJob, result: TaggingResult) -> None:
        dataset_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.SEARCH,
            metadata={
                **(original_job.metadata or {}),
                "stage": "dataset",
                "image_id": result.image_id,
                "tag_count": len(result.generated_tags),
            },
        )
        self.queue_manager.enqueue(QueueType.SEARCH, dataset_job)
