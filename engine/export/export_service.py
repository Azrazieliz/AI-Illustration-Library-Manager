from __future__ import annotations

from pathlib import Path

from engine.export.export_engine import ExportEngine
from engine.export.export_models import ExportCheckpoint, ExportFilter, ExportOptions, ExportResult
from engine.pipeline import PipelineJob, QueueManager, QueueType


class ExportService:
    """Service facade connecting export engine to stage-marked dataset jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: ExportEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or ExportEngine(callback=self._handle_event)

    def process_export_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: ExportCheckpoint | None = None,
    ) -> ExportResult | None:
        if not job.source_path:
            return None

        stage = (job.metadata or {}).get("stage")
        if stage != "export":
            return None

        options = ExportOptions.from_metadata(job.metadata)
        export_filter = ExportFilter.from_metadata(job.metadata)
        result = self.engine.export_path(
            Path(job.source_path),
            checkpoint=checkpoint,
            options=options,
            export_filter=export_filter,
            semantic=job.metadata,
        )
        if result is not None:
            self._publish_collection_job(job, result)
        return result

    def process_export_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: ExportCheckpoint | None = None,
    ) -> list[ExportResult]:
        results: list[ExportResult] = []
        for job in jobs:
            result = self.process_export_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    def _handle_event(self, event: object) -> None:
        return None

    def _publish_collection_job(self, original_job: PipelineJob, result: ExportResult) -> None:
        collection_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.SEARCH,
            metadata={
                **(original_job.metadata or {}),
                "stage": "collection",
                "collection_action": "add_image",
                "collection_name": str((original_job.metadata or {}).get("collection_name", "Library")),
                "collection_kind": str((original_job.metadata or {}).get("collection_kind", "static")),
                "image_id": result.image_id,
                "export_format": result.format_type.value,
            },
        )
        self.queue_manager.enqueue(QueueType.SEARCH, collection_job)
