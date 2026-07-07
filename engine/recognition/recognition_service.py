from __future__ import annotations

from pathlib import Path

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition.recognition_engine import RecognitionEngine
from engine.recognition.recognition_models import RecognitionCheckpoint, RecognitionResult
from engine.recognition.recognition_provider import RecognitionProvider, get_provider


class RecognitionService:
    """Service facade connecting the recognition engine to pipeline queues."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: RecognitionEngine | None = None,
        provider: RecognitionProvider | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()

        if engine is None:
            if provider is None:
                provider = get_provider(provider_type="mock")
            provider.initialize()
            engine = RecognitionEngine(provider=provider, callback=self._handle_event)

        self.engine = engine
        self.provider = provider or engine.provider

    def process_recognition_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: RecognitionCheckpoint | None = None,
    ) -> RecognitionResult | None:
        """Process one RECOGNITION job and publish REVIEW job."""
        if not job.source_path:
            return None

        result = self.engine.process_path(Path(job.source_path), checkpoint=checkpoint)
        if result is None:
            return None

        self._publish_search_job(job, result)
        self._publish_review_job(job, result)
        return result

    def process_recognition_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: RecognitionCheckpoint | None = None,
    ) -> list[RecognitionResult]:
        """Process a batch of RECOGNITION jobs."""
        results: list[RecognitionResult] = []
        for job in jobs:
            result = self.process_recognition_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    def _publish_review_job(self, original_job: PipelineJob, result: RecognitionResult) -> None:
        review_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.REVIEW,
            metadata={**self._result_metadata(result), "review_type": "recognition"},
        )
        self.queue_manager.enqueue(QueueType.REVIEW, review_job)

    def _publish_search_job(self, original_job: PipelineJob, result: RecognitionResult) -> None:
        search_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.SEARCH,
            metadata=self._result_metadata(result),
        )
        self.queue_manager.enqueue(QueueType.SEARCH, search_job)

    def _handle_event(self, event: object) -> None:
        return None

    def _result_metadata(self, result: RecognitionResult) -> dict[str, object]:
        output = result.output
        return {
            "image_id": result.image_id,
            "series": output.series.name if output.series else None,
            "series_confidence": output.series.confidence if output.series else None,
            "characters": [
                {"name": label.name, "confidence": label.confidence}
                for label in output.characters
            ],
            "character_candidates": [
                {
                    "name": candidate.name,
                    "confidence": candidate.confidence,
                    "rank": candidate.rank,
                    "occurrences": candidate.occurrences,
                }
                for candidate in output.character_candidates
            ],
            "overall_confidence": output.overall_confidence,
            "provider_name": output.provider_name,
            "model_name": output.model_name,
            "model_version": output.model_version,
        }
