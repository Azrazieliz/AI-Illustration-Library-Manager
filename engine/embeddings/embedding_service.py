from __future__ import annotations

from pathlib import Path

from engine.embeddings.embedding_engine import EmbeddingEngine
from engine.embeddings.embedding_models import EmbeddingCheckpoint, EmbeddingResult
from engine.embeddings.embedding_provider import EmbeddingProvider, get_provider
from engine.config import settings
from engine.pipeline import PipelineJob, QueueManager, QueueType


class EmbeddingService:
    """Service façade connecting the embedding engine to the pipeline.

    Consumes jobs from the EMBEDDING queue (published by the metadata engine
    and other upstream stages) and stores embeddings in the database
    for use in similarity search and clustering.
    """

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: EmbeddingEngine | None = None,
        provider: EmbeddingProvider | None = None,
        publish_recognition: bool = True,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()

        if engine is None:
            if provider is None:
                provider = get_provider(
                    provider_type=settings.embedding_provider,
                    model_name=settings.embedding_model_name,
                    device=settings.embedding_device,
                )
            engine = EmbeddingEngine(provider=provider, callback=self._handle_event)

        self.engine = engine
        self.provider = provider or engine.provider
        self.publish_recognition = publish_recognition
        self._initialized = False

    # ------------------------------------------------------------------ #
    # Pipeline integration                                                 #
    # ------------------------------------------------------------------ #

    def process_embedding_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: EmbeddingCheckpoint | None = None,
    ) -> EmbeddingResult | None:
        """Process a single EMBEDDING pipeline job.

        1. Extract source_path from the job.
        2. Generate embedding for the image.
        3. Persist embedding through the repository.
        """
        if not job.source_path:
            return None

        self._ensure_provider_initialized()
        path = Path(job.source_path)
        result = self.engine.process_path(path, checkpoint=checkpoint)
        if result is not None and self.publish_recognition:
            self._publish_recognition_job(job, result)
        return result

    def process_embedding_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: EmbeddingCheckpoint | None = None,
    ) -> list[EmbeddingResult]:
        """Process a batch of EMBEDDING pipeline jobs."""
        results: list[EmbeddingResult] = []
        for job in jobs:
            result = self.process_embedding_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _publish_recognition_job(
        self, original_job: PipelineJob, result: EmbeddingResult
    ) -> None:
        """Publish a RECOGNITION queue job for series/character recognition."""
        recognition_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.RECOGNITION,
            metadata={
                "image_id": result.image_id,
                "model_name": result.embedding.model_name,
                "model_version": result.embedding.model_version,
                "dimensions": result.embedding.dimensions,
            },
        )
        self.queue_manager.enqueue(QueueType.RECOGNITION, recognition_job)

    def _handle_event(self, event: object) -> None:
        """Handle events from the engine."""
        return None

    def _ensure_provider_initialized(self) -> None:
        if not self._initialized:
            self.provider.initialize()
            self._initialized = True
