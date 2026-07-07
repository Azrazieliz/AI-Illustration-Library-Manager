from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class AdvancedSortBy(str, Enum):
    SCORE = "score"
    CREATED_AT = "created_at"
    MODIFIED_DATE = "modified_date"
    FILENAME = "filename"
    RATING = "rating"
    WIDTH = "width"
    HEIGHT = "height"


class AdvancedSortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


@dataclass(slots=True)
class AdvancedSearchWeights:
    metadata_score: float = 0.35
    semantic_score: float = 0.35
    tag_score: float = 0.15
    recognition_score: float = 0.15


@dataclass(slots=True)
class AdvancedSearchFilters:
    review_statuses: set[str] | None = None
    include_duplicates: bool | None = None
    min_rating: float | None = None
    max_rating: float | None = None
    min_width: int | None = None
    max_width: int | None = None
    min_height: int | None = None
    max_height: int | None = None
    file_types: set[str] | None = None
    mime_types: set[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    folder_contains: str | None = None
    path_contains: str | None = None
    series: set[str] | None = None
    characters: set[str] | None = None
    tags: set[str] | None = None
    collections: set[str] | None = None


@dataclass(slots=True)
class AdvancedSearchQuery:
    query_text: str = ""
    page: int = 1
    page_size: int = 25
    sort_by: AdvancedSortBy = AdvancedSortBy.SCORE
    sort_direction: AdvancedSortDirection = AdvancedSortDirection.DESC
    filters: AdvancedSearchFilters = field(default_factory=AdvancedSearchFilters)
    weights: AdvancedSearchWeights = field(default_factory=AdvancedSearchWeights)
    semantic_query: str | None = None
    preview_mode: bool = False
    include_facets: bool = True
    include_explanations: bool = True
    use_cache: bool = True
    saved_search_id: str | None = None
    query_id: str | None = None


@dataclass(slots=True)
class AdvancedSearchDocument:
    image_id: int
    path: str
    filename: str
    folder: str
    extension: str
    width: int | None
    height: int | None
    created_at: datetime
    updated_at: datetime
    scan_date: datetime | None
    modified_date: datetime | None
    metadata: dict[str, Any]
    tags: list[str]
    series: str | None
    characters: list[str]
    collections: list[str]
    review_status: str
    rating: float
    has_duplicate: bool
    duplicate_statuses: list[str]
    embedding_vector: list[float]


@dataclass(slots=True)
class AdvancedSearchExplanation:
    metadata_score: float
    semantic_score: float
    tag_score: float
    recognition_score: float
    total_score: float
    matched_fields: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AdvancedSearchResultItem:
    image_id: int
    path: Path
    filename: str
    score: float
    explanation: AdvancedSearchExplanation | None
    preview: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdvancedFacetBucket:
    value: str
    count: int


@dataclass(slots=True)
class AdvancedSearchFacets:
    tags: list[AdvancedFacetBucket] = field(default_factory=list)
    series: list[AdvancedFacetBucket] = field(default_factory=list)
    characters: list[AdvancedFacetBucket] = field(default_factory=list)
    file_types: list[AdvancedFacetBucket] = field(default_factory=list)
    review_statuses: list[AdvancedFacetBucket] = field(default_factory=list)
    duplicate_states: list[AdvancedFacetBucket] = field(default_factory=list)


@dataclass(slots=True)
class AdvancedSearchResponse:
    query: AdvancedSearchQuery
    total: int
    page: int
    page_size: int
    results: list[AdvancedSearchResultItem]
    facets: AdvancedSearchFacets | None = None
    cached: bool = False
    query_id: str | None = None


@dataclass(slots=True)
class AdvancedSavedSearch:
    search_id: str
    name: str
    query: AdvancedSearchQuery
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class AdvancedSearchHistoryEntry:
    query: AdvancedSearchQuery
    total: int
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class AdvancedSearchBatchItem:
    batch_item_id: str
    query: AdvancedSearchQuery


@dataclass(slots=True)
class AdvancedSearchBatchResponse:
    responses: list[AdvancedSearchResponse]


@dataclass(slots=True)
class AdvancedSearchOperationResult:
    action: str
    success: bool
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdvancedSearchCheckpoint:
    processed_job_ids: set[str] = field(default_factory=set)
    cancelled_job_ids: set[str] = field(default_factory=set)
    processed_batch_item_ids: set[str] = field(default_factory=set)

    def add_processed_job(self, job_id: str) -> None:
        self.processed_job_ids.add(str(job_id))

    def is_processed_job(self, job_id: str) -> bool:
        return str(job_id) in self.processed_job_ids

    def add_processed_batch_item(self, batch_item_id: str) -> None:
        self.processed_batch_item_ids.add(str(batch_item_id))

    def is_processed_batch_item(self, batch_item_id: str) -> bool:
        return str(batch_item_id) in self.processed_batch_item_ids

    def cancel(self, job_id: str) -> None:
        self.cancelled_job_ids.add(str(job_id))

    def resume(self, job_id: str) -> None:
        self.cancelled_job_ids.discard(str(job_id))

    def is_cancelled(self, job_id: str) -> bool:
        return str(job_id) in self.cancelled_job_ids
