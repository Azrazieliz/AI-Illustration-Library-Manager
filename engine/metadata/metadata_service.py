from __future__ import annotations

from pathlib import Path

from engine.metadata.metadata_engine import MetadataEngine
from engine.metadata.metadata_models import MetadataCheckpoint, MetadataResult
from engine.pipeline import PipelineJob, QueueManager, QueueType


class MetadataService:
    """Service façade connecting the metadata engine to the pipeline.

    Consumes jobs from the METADATA queue (published by the thumbnail engine
    and other upstream stages) and publishes SEARCH queue jobs so the search
    indexing stage can process the enriched metadata next.
    """

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: MetadataEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or MetadataEngine(callback=self._handle_event)

    # ------------------------------------------------------------------ #
    # Pipeline integration                                                 #
    # ------------------------------------------------------------------ #

    def process_metadata_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: MetadataCheckpoint | None = None,
    ) -> MetadataResult | None:
        """Process a single METADATA pipeline job.

        1. Extract source_path from the job.
        2. Extract metadata from the image.
        3. Persist metadata through the repository.
        4. Publish a SEARCH queue job with extracted metadata.
        """
        if not job.source_path:
            return None

        path = Path(job.source_path)
        result = self.engine.process_path(path, checkpoint=checkpoint)
        if result is None:
            return None

        self._publish_search_job(job, result)
        return result

    def process_metadata_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: MetadataCheckpoint | None = None,
    ) -> list[MetadataResult]:
        """Process a batch of METADATA pipeline jobs."""
        results: list[MetadataResult] = []
        for job in jobs:
            result = self.process_metadata_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _publish_search_job(
        self, original_job: PipelineJob, result: MetadataResult
    ) -> None:
        """Publish a SEARCH queue job with metadata for indexing."""
        search_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.SEARCH,
            metadata={
                "image_id": result.image_id,
                "mime_type": result.metadata.mime_type,
                "width": result.metadata.width,
                "height": result.metadata.height,
                "aspect_ratio": result.metadata.aspect_ratio,
                "orientation": result.metadata.orientation,
                "color_mode": result.metadata.color_mode,
                "bit_depth": result.metadata.bit_depth,
                "dpi": result.metadata.dpi,
                "has_icc_profile": result.metadata.has_icc_profile,
                "is_animated": result.metadata.is_animated,
                "frame_count": result.metadata.frame_count,
            },
        )
        self.queue_manager.enqueue(QueueType.SEARCH, search_job)

    def _handle_event(self, event: object) -> None:
        """Handle events from the engine."""
        # Events can be logged or dispatched to an event bus here
        pass
