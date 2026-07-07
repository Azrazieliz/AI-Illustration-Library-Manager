from __future__ import annotations

from pathlib import Path
from typing import Callable

from engine.hashing.hash_engine import HashEngine
from engine.hashing.hash_models import DuplicateCandidate, HashCheckpoint, HashResult
from engine.pipeline import PipelineJob, QueueManager, QueueType


class HashService:
    """Service façade that connects the hash engine to the pipeline.

    Consumes jobs from the HASH queue and publishes :data:`QueueType.DUPLICATE`
    jobs for every successfully hashed file so the duplicate detection stage
    can proceed independently.
    """

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        hash_engine: HashEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.hash_engine = hash_engine or HashEngine(callback=self._handle_event)

    # ------------------------------------------------------------------ #
    # Pipeline integration                                                 #
    # ------------------------------------------------------------------ #

    def process_hash_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: HashCheckpoint | None = None,
    ) -> DuplicateCandidate | None:
        """Process a single HASH pipeline job.

        1. Hash the file at ``job.source_path``.
        2. Look up the corresponding image record.
        3. Publish a DUPLICATE queue job with hash metadata attached.
        4. Return a :class:`DuplicateCandidate` for the caller (or ``None``
           when the file is missing or has no image record).
        """
        if not job.source_path:
            return None

        path = Path(job.source_path)
        result: HashResult | None = self.hash_engine.hash_path(path, checkpoint=checkpoint)
        if result is None:
            return None

        image = self.hash_engine.image_repository.get_by_path(job.source_path)
        if image is None:
            return None

        candidate = self.hash_engine.make_duplicate_candidate(result, image.id)
        self._publish_duplicate_job(job, result)
        return candidate

    def process_hash_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: HashCheckpoint | None = None,
    ) -> list[DuplicateCandidate]:
        """Process a batch of HASH pipeline jobs."""
        candidates: list[DuplicateCandidate] = []
        for job in jobs:
            candidate = self.process_hash_job(job, checkpoint=checkpoint)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _publish_duplicate_job(self, original_job: PipelineJob, result: HashResult) -> None:
        dup_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.DUPLICATE,
            metadata={
                "sha256": result.sha256,
                "phash": result.phash,
                "ahash": result.ahash,
                "dhash": result.dhash,
            },
        )
        self.queue_manager.enqueue(QueueType.DUPLICATE, dup_job)

    def _handle_event(self, event: object) -> None:
        return None
