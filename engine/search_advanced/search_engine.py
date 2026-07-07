from __future__ import annotations

from typing import Callable

from engine.logging import get_logger
from engine.repositories.advanced_search_repository import AdvancedSearchRepository
from engine.search_advanced.search_builder import AdvancedSearchBuilder
from engine.search_advanced.search_models import (
    AdvancedSavedSearch,
    AdvancedSearchBatchItem,
    AdvancedSearchBatchResponse,
    AdvancedSearchCheckpoint,
    AdvancedSearchQuery,
    AdvancedSearchResponse,
)
from engine.search_advanced.search_statistics import AdvancedSearchStatistics


class AdvancedSearchEngine:
    """Orchestrates advanced hybrid querying and stateful search features."""

    def __init__(
        self,
        *,
        repository: AdvancedSearchRepository | None = None,
        builder: AdvancedSearchBuilder | None = None,
        callback: Callable[[object], None] | None = None,
    ) -> None:
        self.builder = builder or AdvancedSearchBuilder()
        self.repository = repository or AdvancedSearchRepository(builder=self.builder)
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = AdvancedSearchStatistics()

    def search(self, query: AdvancedSearchQuery) -> AdvancedSearchResponse:
        self.builder.validate_query(query)
        self.statistics.increment_searches()
        response, cached, scanned = self.repository.search(query)
        self.statistics.add_documents_scanned(scanned)
        if cached:
            self.statistics.increment_cache_hit()
        else:
            self.statistics.increment_cache_miss()
        return response

    def batch_search(
        self,
        items: list[AdvancedSearchBatchItem],
        *,
        checkpoint: AdvancedSearchCheckpoint | None = None,
        cancelled: bool = False,
    ) -> AdvancedSearchBatchResponse:
        self.statistics.increment_batch_searches()
        processed = checkpoint.processed_batch_item_ids if checkpoint is not None else None
        result = self.repository.batch_search(items, processed_batch_item_ids=processed, cancelled_job=cancelled)
        if checkpoint is not None:
            for response in result.responses:
                if response.query_id is not None:
                    checkpoint.add_processed_batch_item(response.query_id)
        return result

    def save_search(self, *, name: str, query: AdvancedSearchQuery) -> AdvancedSavedSearch:
        return self.repository.save_search(name=name, query=query)

    def run_saved_search(self, search_id: str) -> AdvancedSearchResponse | None:
        saved = self.repository.get_saved_search(search_id)
        if saved is None:
            return None
        return self.search(saved.query)

    def list_saved_searches(self) -> list[AdvancedSavedSearch]:
        return self.repository.list_saved_searches()

    def delete_saved_search(self, search_id: str) -> bool:
        return self.repository.delete_saved_search(search_id)

    def history(self):
        return self.repository.search_history()

    def invalidate_cache(self) -> None:
        self.repository.invalidate_cache()
