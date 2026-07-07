from __future__ import annotations

from pathlib import Path

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.search.search_engine import SearchEngine
from engine.search.search_models import SearchCheckpoint, SearchIndexResult, SearchResult


class SearchService:
    """Service facade connecting semantic search engine to pipeline queues."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: SearchEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or SearchEngine(callback=self._handle_event)

    def process_search_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: SearchCheckpoint | None = None,
    ) -> SearchIndexResult | None:
        """Consume SEARCH queue job and index semantic record."""
        if not job.source_path:
            return None
        return self.engine.index_path(Path(job.source_path), checkpoint=checkpoint)

    def process_search_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: SearchCheckpoint | None = None,
    ) -> list[SearchIndexResult]:
        """Process a batch of SEARCH jobs."""
        results: list[SearchIndexResult] = []
        for job in jobs:
            result = self.process_search_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    def query(
        self,
        *,
        query_vector: list[float],
        top_k: int = 10,
        min_similarity: float = 0.0,
    ) -> SearchResult:
        """Query semantic search index."""
        return self.engine.search(
            query_vector=query_vector,
            top_k=top_k,
            min_similarity=min_similarity,
        )

    def _handle_event(self, event: object) -> None:
        return None
