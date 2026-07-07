from __future__ import annotations

from engine.collections.collection_engine import CollectionEngine
from engine.collections.collection_models import (
    CollectionCheckpoint,
    CollectionHierarchyNode,
    CollectionJobPayload,
    CollectionKind,
    CollectionOperationResult,
    CollectionSummary,
)
from engine.pipeline import PipelineJob, QueueManager


class CollectionService:
    """Service facade connecting collection engine to stage-marked jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: CollectionEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or CollectionEngine(callback=self._handle_event)

    def process_collection_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: CollectionCheckpoint | None = None,
    ) -> CollectionOperationResult | None:
        if not job.source_path:
            return None

        stage = (job.metadata or {}).get("stage")
        if stage != "collection":
            return None

        payload = CollectionJobPayload.from_metadata(job.metadata)
        return self.engine.process_job(payload, checkpoint=checkpoint)

    def process_collection_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: CollectionCheckpoint | None = None,
    ) -> list[CollectionOperationResult]:
        results: list[CollectionOperationResult] = []
        for job in jobs:
            result = self.process_collection_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    def create_collection(
        self,
        *,
        name: str,
        kind: CollectionKind = CollectionKind.STATIC,
        parent_id: int | None = None,
        metadata: dict | None = None,
        smart_rule: dict | None = None,
    ) -> CollectionOperationResult:
        return self.engine.create_collection(
            name=name,
            kind=kind,
            parent_id=parent_id,
            metadata=metadata,
            smart_rule=smart_rule,
        )

    def summary(self, collection_id: int) -> CollectionSummary | None:
        return self.engine.summary(collection_id)

    def hierarchy(self) -> list[CollectionHierarchyNode]:
        return self.engine.hierarchy()

    def _handle_event(self, event: object) -> None:
        return None
