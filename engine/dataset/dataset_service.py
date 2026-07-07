from __future__ import annotations

from pathlib import Path

from engine.dataset.dataset_engine import DatasetEngine
from engine.dataset.dataset_models import DatasetBuildResult, DatasetCheckpoint
from engine.pipeline import PipelineJob, QueueManager, QueueType


class DatasetService:
    """Service facade connecting dataset engine to stage-marked jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: DatasetEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or DatasetEngine(callback=self._handle_event)

    def process_dataset_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: DatasetCheckpoint | None = None,
        rebuild: bool = False,
    ) -> DatasetBuildResult | None:
        if not job.source_path:
            return None

        stage = (job.metadata or {}).get("stage")
        if stage != "dataset":
            return None

        result = self.engine.build_path(
            Path(job.source_path),
            checkpoint=checkpoint,
            rebuild=rebuild,
            semantic=job.metadata,
        )
        if result is not None:
            self._publish_export_job(job, result)
        return result

    def process_dataset_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: DatasetCheckpoint | None = None,
        rebuild: bool = False,
    ) -> list[DatasetBuildResult]:
        results: list[DatasetBuildResult] = []
        for job in jobs:
            result = self.process_dataset_job(job, checkpoint=checkpoint, rebuild=rebuild)
            if result is not None:
                results.append(result)
        return results

    def _handle_event(self, event: object) -> None:
        return None

    def _publish_export_job(self, original_job: PipelineJob, result: DatasetBuildResult) -> None:
        export_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.SEARCH,
            metadata={
                **(original_job.metadata or {}),
                "stage": "export",
                "image_id": result.image_id,
                "dataset_rebuilt": result.rebuilt,
            },
        )
        self.queue_manager.enqueue(QueueType.SEARCH, export_job)
