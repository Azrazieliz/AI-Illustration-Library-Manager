from __future__ import annotations

from engine.duplicates.duplicate_engine import DuplicateEngine
from engine.duplicates.duplicate_models import (
    DuplicateCheckpoint,
    DuplicatePair,
)
from engine.hashing.hash_models import DuplicateCandidate
from engine.pipeline import PipelineJob, QueueManager, QueueType


class DuplicateService:
    """Service façade that bridges the duplicate engine and the pipeline.

    Consumes jobs from the DUPLICATE queue (published by the hash engine) and
    publishes REVIEW queue jobs for every confirmed duplicate pair so the
    review stage can act on them independently.
    """

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: DuplicateEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or DuplicateEngine(callback=self._handle_event)

    # ------------------------------------------------------------------ #
    # Pipeline integration                                                 #
    # ------------------------------------------------------------------ #

    def process_duplicate_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: DuplicateCheckpoint | None = None,
    ) -> list[DuplicatePair]:
        """Process a single DUPLICATE pipeline job.

        Extracts the :class:`DuplicateCandidate` from the job's metadata,
        runs it through the engine, and publishes a REVIEW job for every
        confirmed duplicate pair that is found.
        """
        candidate = self._extract_candidate(job)
        if candidate is None:
            return []

        pairs = self.engine.process_candidate(candidate, checkpoint=checkpoint)
        for pair in pairs:
            self._publish_review_job(pair)
        return pairs

    def process_duplicate_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: DuplicateCheckpoint | None = None,
    ) -> list[DuplicatePair]:
        """Process a batch of DUPLICATE pipeline jobs."""
        all_pairs: list[DuplicatePair] = []
        for job in jobs:
            all_pairs.extend(self.process_duplicate_job(job, checkpoint=checkpoint))
        return all_pairs

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _extract_candidate(self, job: PipelineJob) -> DuplicateCandidate | None:
        if not job.source_path:
            return None
        meta = job.metadata or {}
        sha256 = meta.get("sha256", "")
        if not sha256:
            return None
        image = self.engine.image_repository.get_by_path(job.source_path)
        if image is None:
            return None
        return DuplicateCandidate(
            source_path=job.source_path,
            image_id=image.id,
            sha256=sha256,
            phash=meta.get("phash"),
            ahash=meta.get("ahash"),
            dhash=meta.get("dhash"),
        )

    def _publish_review_job(self, pair: DuplicatePair) -> None:
        job = PipelineJob(
            source_path=pair.source_path_a,
            queue_type=QueueType.REVIEW,
            metadata={
                "image_a_id": pair.image_a_id,
                "image_b_id": pair.image_b_id,
                "match_type": pair.match_type.value,
                "confidence": pair.confidence.value,
                "overall_score": pair.overall_score,
            },
        )
        self.queue_manager.enqueue(QueueType.REVIEW, job)

    def _handle_event(self, event: object) -> None:
        return None
