from __future__ import annotations

from pathlib import Path

from engine.thumbnails.thumbnail_engine import ThumbnailEngine
from engine.thumbnails.thumbnail_models import ThumbnailCheckpoint, ThumbnailResult
from engine.pipeline import PipelineJob, QueueManager, QueueType


class ThumbnailService:
    """Service façade connecting the thumbnail engine to the pipeline.

    Consumes jobs from the REVIEW queue (published by the duplicate engine
    and other upstream stages) and publishes METADATA queue jobs so the
    metadata enrichment stage can process the images next.
    """

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: ThumbnailEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or ThumbnailEngine(callback=self._handle_event)

    # ------------------------------------------------------------------ #
    # Pipeline integration                                                 #
    # ------------------------------------------------------------------ #

    def process_review_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: ThumbnailCheckpoint | None = None,
    ) -> ThumbnailResult | None:
        """Process a single REVIEW pipeline job.

        1. Extract ``source_path`` from the job.
        2. Generate (or serve from cache) all thumbnails.
        3. Publish a METADATA queue job with thumbnail file paths.
        """
        if not job.source_path:
            return None

        path = Path(job.source_path)
        result = self.engine.process_path(path, checkpoint=checkpoint)
        if result is None:
            return None

        self._publish_metadata_job(job, result)
        return result

    def process_review_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: ThumbnailCheckpoint | None = None,
    ) -> list[ThumbnailResult]:
        """Process a batch of REVIEW pipeline jobs."""
        results: list[ThumbnailResult] = []
        for job in jobs:
            result = self.process_review_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _publish_metadata_job(
        self, original_job: PipelineJob, result: ThumbnailResult
    ) -> None:
        meta_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.METADATA,
            metadata={
                "image_id": result.image_id,
                "thumbnail_sizes": [t.spec.size for t in result.thumbnails],
                "thumbnail_paths": [str(t.file_path) for t in result.thumbnails],
                "from_cache": result.from_cache,
            },
        )
        self.queue_manager.enqueue(QueueType.METADATA, meta_job)

    def _handle_event(self, event: object) -> None:
        return None
