from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.knowledge_base.knowledge_base_engine import KnowledgeBaseEngine
from engine.knowledge_base.knowledge_base_models import (
    KnowledgeBaseCheckpoint,
    KnowledgeBaseImportFormat,
    KnowledgeBaseOperationResult,
    KnowledgeBaseTaskType,
)
from engine.pipeline import PipelineJob, QueueManager, QueueType


class KnowledgeBaseService:
    """Service facade connecting knowledge-base engine to pipeline jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: KnowledgeBaseEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or KnowledgeBaseEngine()

    def process_knowledge_base_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: KnowledgeBaseCheckpoint | None = None,
    ) -> KnowledgeBaseOperationResult | None:
        if not job.source_path and not (job.metadata or {}).get("payload"):
            return None

        stage = (job.metadata or {}).get("stage")
        if stage != "knowledge_base":
            return None

        action = str((job.metadata or {}).get("action", "import")).lower()
        result = self._dispatch(job, action=action)
        if result is not None:
            self._publish_follow_up(job, result)
            if checkpoint is not None:
                checkpoint.add_processed(str(job.id))
        return result

    def process_knowledge_base_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: KnowledgeBaseCheckpoint | None = None,
    ) -> list[KnowledgeBaseOperationResult]:
        results: list[KnowledgeBaseOperationResult] = []
        for job in jobs:
            result = self.process_knowledge_base_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    def _dispatch(self, job: PipelineJob, *, action: str) -> KnowledgeBaseOperationResult | None:
        metadata = job.metadata or {}
        if action == "import":
            format_value = metadata.get("format", KnowledgeBaseImportFormat.JSON)
            payload = metadata.get("payload")
            if payload is None and job.source_path:
                payload = Path(job.source_path).read_text(encoding="utf-8")
            dataset = self.engine.import_dataset(payload, format=format_value, merge=bool(metadata.get("merge", False)))
            return KnowledgeBaseOperationResult(
                action=KnowledgeBaseTaskType.IMPORT,
                success=True,
                message="Imported knowledge-base dataset.",
                dataset_id=dataset.dataset_id,
                payload={"dataset": dataset.name},
            )
        if action == "export":
            dataset_id = int(metadata["dataset_id"])
            format_value = metadata.get("format", KnowledgeBaseImportFormat.JSON)
            payload = self.engine.export_dataset(dataset_id, format=format_value)
            output_path = metadata.get("output_path")
            if output_path is not None:
                path = Path(output_path)
                if isinstance(payload, str):
                    path.write_text(payload, encoding="utf-8")
                else:
                    path.write_text(self.engine.builder.serialize_bundle(payload, format=KnowledgeBaseImportFormat.JSON), encoding="utf-8")
            return KnowledgeBaseOperationResult(
                action=KnowledgeBaseTaskType.EXPORT,
                success=True,
                message="Exported knowledge-base dataset.",
                dataset_id=dataset_id,
                payload={"export": payload},
            )
        if action == "validate":
            dataset_id = metadata.get("dataset_id")
            report = self.engine.validate(dataset_id=int(dataset_id) if dataset_id is not None else None)
            return KnowledgeBaseOperationResult(
                action=KnowledgeBaseTaskType.VALIDATE,
                success=report.valid,
                message="Validation complete.",
                dataset_id=int(dataset_id) if dataset_id is not None else None,
                payload={"report": report},
            )
        if action == "rebuild":
            snapshot = self.engine.rebuild_statistics()
            return KnowledgeBaseOperationResult(
                action=KnowledgeBaseTaskType.REBUILD,
                success=True,
                message="Statistics and counts rebuilt.",
                payload={"statistics": snapshot},
            )
        if action == "statistics":
            snapshot = self.engine.statistics_snapshot()
            return KnowledgeBaseOperationResult(
                action=KnowledgeBaseTaskType.STATISTICS,
                success=True,
                message="Statistics snapshot generated.",
                payload={"statistics": snapshot},
            )
        return None

    def _publish_follow_up(self, original_job: PipelineJob, result: KnowledgeBaseOperationResult) -> None:
        if result.action is KnowledgeBaseTaskType.EXPORT:
            queue_job = PipelineJob(
                source_path=original_job.source_path,
                queue_type=QueueType.SEARCH,
                metadata={
                    **(original_job.metadata or {}),
                    "stage": "knowledge_base_export",
                    "dataset_id": result.dataset_id,
                },
            )
            self.queue_manager.enqueue(QueueType.SEARCH, queue_job)
