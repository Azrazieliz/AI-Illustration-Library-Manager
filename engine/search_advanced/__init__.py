from importlib import import_module

__all__ = [
    "AdvancedFacetBucket",
    "AdvancedSavedSearch",
    "AdvancedSearchBatchItem",
    "AdvancedSearchBatchResponse",
    "AdvancedSearchBuilder",
    "AdvancedSearchCheckpoint",
    "AdvancedSearchDocument",
    "AdvancedSearchEngine",
    "AdvancedSearchException",
    "AdvancedSearchExplanation",
    "AdvancedSearchFacets",
    "AdvancedSearchFilters",
    "AdvancedSearchHistoryEntry",
    "AdvancedSearchOperationResult",
    "AdvancedSearchParseError",
    "AdvancedSearchPersistenceError",
    "AdvancedSearchQuery",
    "AdvancedSearchQueryError",
    "AdvancedSearchResponse",
    "AdvancedSearchResultItem",
    "AdvancedSearchService",
    "AdvancedSearchStatistics",
    "AdvancedSearchWeights",
    "AdvancedSearchWorker",
    "AdvancedSortBy",
    "AdvancedSortDirection",
]


_EXPORT_MAP = {
    "AdvancedFacetBucket": "engine.search_advanced.search_models",
    "AdvancedSavedSearch": "engine.search_advanced.search_models",
    "AdvancedSearchBatchItem": "engine.search_advanced.search_models",
    "AdvancedSearchBatchResponse": "engine.search_advanced.search_models",
    "AdvancedSearchBuilder": "engine.search_advanced.search_builder",
    "AdvancedSearchCheckpoint": "engine.search_advanced.search_models",
    "AdvancedSearchDocument": "engine.search_advanced.search_models",
    "AdvancedSearchEngine": "engine.search_advanced.search_engine",
    "AdvancedSearchException": "engine.search_advanced.search_exceptions",
    "AdvancedSearchExplanation": "engine.search_advanced.search_models",
    "AdvancedSearchFacets": "engine.search_advanced.search_models",
    "AdvancedSearchFilters": "engine.search_advanced.search_models",
    "AdvancedSearchHistoryEntry": "engine.search_advanced.search_models",
    "AdvancedSearchOperationResult": "engine.search_advanced.search_models",
    "AdvancedSearchParseError": "engine.search_advanced.search_exceptions",
    "AdvancedSearchPersistenceError": "engine.search_advanced.search_exceptions",
    "AdvancedSearchQuery": "engine.search_advanced.search_models",
    "AdvancedSearchQueryError": "engine.search_advanced.search_exceptions",
    "AdvancedSearchResponse": "engine.search_advanced.search_models",
    "AdvancedSearchResultItem": "engine.search_advanced.search_models",
    "AdvancedSearchService": "engine.search_advanced.search_service",
    "AdvancedSearchStatistics": "engine.search_advanced.search_statistics",
    "AdvancedSearchWeights": "engine.search_advanced.search_models",
    "AdvancedSearchWorker": "engine.search_advanced.search_worker",
    "AdvancedSortBy": "engine.search_advanced.search_models",
    "AdvancedSortDirection": "engine.search_advanced.search_models",
}


def __getattr__(name: str):
    module_name = _EXPORT_MAP.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    return getattr(module, name)
