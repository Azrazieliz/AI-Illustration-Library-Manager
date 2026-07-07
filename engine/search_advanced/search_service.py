from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.search_advanced.search_engine import AdvancedSearchEngine
from engine.search_advanced.search_models import (
    AdvancedSearchBatchItem,
    AdvancedSearchCheckpoint,
    AdvancedSearchOperationResult,
)


class AdvancedSearchService:
    """Service facade connecting advanced search operations to SEARCH queue jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: AdvancedSearchEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or AdvancedSearchEngine()

    def process_advanced_search_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: AdvancedSearchCheckpoint | None = None,
    ) -> AdvancedSearchOperationResult | None:
        metadata = job.metadata or {}
        stage = metadata.get("stage")
        if stage != "advanced_search":
            return None

        if checkpoint is not None and checkpoint.is_processed_job(str(job.id)):
            return None

        action = str(metadata.get("action", "search")).lower()
        result = self._dispatch(action=action, metadata=metadata, source_path=job.source_path)
        if checkpoint is not None and result is not None:
            checkpoint.add_processed_job(str(job.id))
        return result

    def process_advanced_search_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: AdvancedSearchCheckpoint | None = None,
    ) -> list[AdvancedSearchOperationResult]:
        out: list[AdvancedSearchOperationResult] = []
        for job in jobs:
            result = self.process_advanced_search_job(job, checkpoint=checkpoint)
            if result is not None:
                out.append(result)
        return out

    def _dispatch(self, *, action: str, metadata: dict[str, Any], source_path: str | None) -> AdvancedSearchOperationResult | None:
        if action == "search":
            query = self.engine.builder.query_from_payload(dict(metadata.get("query", {})))
            response = self.engine.search(query)
            return AdvancedSearchOperationResult(
                action="search",
                success=True,
                message="Advanced search executed.",
                payload={"response": response},
            )

        if action == "batch":
            items_payload = list(metadata.get("batch_items", []))
            batch_items = [
                AdvancedSearchBatchItem(
                    batch_item_id=str(item.get("batch_item_id") or index),
                    query=self.engine.builder.query_from_payload(dict(item.get("query", {}))),
                )
                for index, item in enumerate(items_payload)
            ]
            response = self.engine.batch_search(batch_items)
            return AdvancedSearchOperationResult(
                action="batch",
                success=True,
                message="Batch advanced search executed.",
                payload={"response": response},
            )

        if action == "save":
            query = self.engine.builder.query_from_payload(dict(metadata.get("query", {})))
            name = str(metadata.get("name", "saved-search")).strip() or "saved-search"
            saved = self.engine.save_search(name=name, query=query)
            return AdvancedSearchOperationResult(
                action="save",
                success=True,
                message="Saved search created.",
                payload={"saved": saved},
            )

        if action == "run_saved":
            search_id = str(metadata.get("search_id", "")).strip()
            if not search_id:
                return AdvancedSearchOperationResult(action="run_saved", success=False, message="search_id is required")
            response = self.engine.run_saved_search(search_id)
            return AdvancedSearchOperationResult(
                action="run_saved",
                success=response is not None,
                message="Saved search executed." if response is not None else "Saved search not found.",
                payload={"response": response} if response is not None else {},
            )

        if action == "invalidate_cache":
            self.engine.invalidate_cache()
            return AdvancedSearchOperationResult(
                action="invalidate_cache",
                success=True,
                message="Advanced search cache invalidated.",
            )

        if action == "search_from_file" and source_path:
            payload = Path(source_path).read_text(encoding="utf-8")
            query = self.engine.builder.query_from_payload({"query_text": payload})
            response = self.engine.search(query)
            return AdvancedSearchOperationResult(
                action="search_from_file",
                success=True,
                message="Advanced search from file executed.",
                payload={"response": response},
            )

        return None
