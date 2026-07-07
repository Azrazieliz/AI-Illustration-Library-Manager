from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from engine.database.models.image import Image
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.review_repository import ReviewRepository
from engine.search_advanced.search_builder import AdvancedSearchBuilder
from engine.search_advanced.search_models import (
    AdvancedFacetBucket,
    AdvancedSavedSearch,
    AdvancedSearchBatchItem,
    AdvancedSearchBatchResponse,
    AdvancedSearchDocument,
    AdvancedSearchExplanation,
    AdvancedSearchFacets,
    AdvancedSearchHistoryEntry,
    AdvancedSearchQuery,
    AdvancedSearchResponse,
    AdvancedSearchResultItem,
    AdvancedSortBy,
    AdvancedSortDirection,
)


class AdvancedSearchRepository:
    """Hybrid advanced search repository built on top of existing repositories."""

    def __init__(
        self,
        *,
        image_repository: ImageRepository | None = None,
        metadata_repository: MetadataRepository | None = None,
        embedding_repository: EmbeddingRepository | None = None,
        duplicate_repository: DuplicateRepository | None = None,
        review_repository: ReviewRepository | None = None,
        builder: AdvancedSearchBuilder | None = None,
    ) -> None:
        self.image_repository = image_repository or ImageRepository()
        self.metadata_repository = metadata_repository or MetadataRepository()
        self.embedding_repository = embedding_repository or EmbeddingRepository()
        self.duplicate_repository = duplicate_repository or DuplicateRepository()
        self.review_repository = review_repository or ReviewRepository()
        self.builder = builder or AdvancedSearchBuilder()

        self._saved_searches: dict[str, AdvancedSavedSearch] = {}
        self._search_history: list[AdvancedSearchHistoryEntry] = []
        self._query_cache: dict[str, AdvancedSearchResponse] = {}

    # ------------------------------------------------------------------
    # Saved search and history
    # ------------------------------------------------------------------
    def save_search(self, *, name: str, query: AdvancedSearchQuery) -> AdvancedSavedSearch:
        search_id = str(uuid4())
        saved = AdvancedSavedSearch(search_id=search_id, name=name, query=replace(query))
        self._saved_searches[search_id] = saved
        return saved

    def list_saved_searches(self) -> list[AdvancedSavedSearch]:
        return [self._saved_searches[key] for key in sorted(self._saved_searches.keys())]

    def get_saved_search(self, search_id: str) -> AdvancedSavedSearch | None:
        return self._saved_searches.get(search_id)

    def delete_saved_search(self, search_id: str) -> bool:
        if search_id not in self._saved_searches:
            return False
        del self._saved_searches[search_id]
        return True

    def search_history(self) -> list[AdvancedSearchHistoryEntry]:
        return list(self._search_history)

    def invalidate_cache(self) -> None:
        self._query_cache = {}

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------
    def search(self, query: AdvancedSearchQuery) -> tuple[AdvancedSearchResponse, bool, int]:
        documents = self._build_documents()
        corpus_signature = self._corpus_signature(documents)
        cache_key = self.builder.build_query_cache_key(query, corpus_signature)

        if query.use_cache and cache_key in self._query_cache:
            cached = self._query_cache[cache_key]
            return cached, True, 0

        ast = self.builder.parse_query(query.query_text)
        semantic_text = query.semantic_query if query.semantic_query else query.query_text
        semantic_vector = self.builder.vector_from_seed(semantic_text or "semantic-empty")
        query_tokens = self.builder.tokenize_text(query.query_text)

        scored: list[tuple[AdvancedSearchDocument, AdvancedSearchExplanation]] = []
        scanned = 0
        for document in documents:
            scanned += 1
            if not self._passes_filters(document, query):
                continue

            matched, matched_count, total_count, matched_fields, matched_terms = self.builder.evaluate(ast, document)
            if not matched:
                continue

            metadata_score = (float(matched_count) / float(total_count)) if total_count > 0 else 0.0
            semantic_score = self.builder.cosine_similarity(semantic_vector, document.embedding_vector)
            tag_score = self._tag_overlap_score(query_tokens, document.tags)
            recognition_score = self._recognition_overlap_score(query_tokens, document.series, document.characters)

            total_score = self._weighted_score(
                metadata_score=metadata_score,
                semantic_score=semantic_score,
                tag_score=tag_score,
                recognition_score=recognition_score,
                query=query,
            )
            scored.append(
                (
                    document,
                    AdvancedSearchExplanation(
                        metadata_score=round(metadata_score, 4),
                        semantic_score=round(semantic_score, 4),
                        tag_score=round(tag_score, 4),
                        recognition_score=round(recognition_score, 4),
                        total_score=round(total_score, 4),
                        matched_fields=sorted(matched_fields),
                        matched_terms=sorted(matched_terms),
                    ),
                )
            )

        scored = self._sort_results(scored, query)
        total = len(scored)

        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        page_items = scored[start:end]

        result_items = [
            AdvancedSearchResultItem(
                image_id=document.image_id,
                path=Path(document.path),
                filename=document.filename,
                score=explanation.total_score,
                explanation=explanation if query.include_explanations else None,
                preview=self._build_preview(document) if query.preview_mode else {},
            )
            for document, explanation in page_items
        ]

        facets = self._build_facets([item[0] for item in scored]) if query.include_facets else None
        response = AdvancedSearchResponse(
            query=replace(query),
            total=total,
            page=query.page,
            page_size=query.page_size,
            results=result_items,
            facets=facets,
            cached=False,
            query_id=query.query_id,
        )

        self._search_history.append(AdvancedSearchHistoryEntry(query=replace(query), total=total))
        self._search_history = self._search_history[-200:]

        if query.use_cache:
            self._query_cache[cache_key] = response

        return response, False, scanned

    def batch_search(
        self,
        items: list[AdvancedSearchBatchItem],
        *,
        processed_batch_item_ids: set[str] | None = None,
        cancelled_job: bool = False,
    ) -> AdvancedSearchBatchResponse:
        processed = processed_batch_item_ids or set()
        responses: list[AdvancedSearchResponse] = []
        for item in items:
            if cancelled_job:
                break
            if item.batch_item_id in processed:
                continue
            result, _, _ = self.search(item.query)
            result.query_id = item.batch_item_id
            responses.append(result)
        return AdvancedSearchBatchResponse(responses=responses)

    # ------------------------------------------------------------------
    # Internal data preparation
    # ------------------------------------------------------------------
    def _build_documents(self) -> list[AdvancedSearchDocument]:
        images = self.image_repository.list_images()
        metadata_by_image = {item.image_id: item for item in self.metadata_repository.list_all_metadata()}
        embedding_by_image = {item.image_id: item for item in self.embedding_repository.list_all_embeddings()}

        duplicate_status_by_image: dict[int, list[str]] = {}
        for duplicate in self.duplicate_repository.list_all_duplicates():
            duplicate_status_by_image.setdefault(duplicate.image_a_id, []).append(str(duplicate.status))
            duplicate_status_by_image.setdefault(duplicate.image_b_id, []).append(str(duplicate.status))

        latest_review_by_image: dict[int, tuple[datetime, str, float]] = {}
        for review in self.review_repository.list_review_items():
            previous = latest_review_by_image.get(review.image_id)
            if previous is None or review.timestamp >= previous[0]:
                latest_review_by_image[review.image_id] = (review.timestamp, review.status.value, float(review.confidence))

        documents: list[AdvancedSearchDocument] = []
        for image in images:
            metadata = metadata_by_image.get(image.id)
            embedding = embedding_by_image.get(image.id)
            review = latest_review_by_image.get(image.id)
            duplicate_statuses = sorted(set(duplicate_status_by_image.get(image.id, [])))

            path_parts = [self.builder.normalize_text(part) for part in Path(str(image.original_path)).parts if part]
            derived_collections = sorted({part for part in path_parts[-3:-1] if part})

            documents.append(
                AdvancedSearchDocument(
                    image_id=image.id,
                    path=str(image.original_path),
                    filename=image.filename,
                    folder=Path(image.original_path).parent.as_posix(),
                    extension=(image.extension or "").lstrip(".").lower(),
                    width=image.width,
                    height=image.height,
                    created_at=image.created_at,
                    updated_at=image.updated_at,
                    scan_date=image.scan_date,
                    modified_date=image.modified_date,
                    metadata={
                        "mime_type": metadata.mime_type if metadata is not None else None,
                        "orientation": metadata.orientation if metadata is not None else None,
                        "color_mode": metadata.color_mode if metadata is not None else None,
                        "is_animated": metadata.is_animated if metadata is not None else False,
                        "aspect_ratio": metadata.aspect_ratio if metadata is not None else None,
                        "dpi": metadata.dpi if metadata is not None else None,
                        "exif_data": metadata.exif_data if metadata is not None else None,
                    },
                    tags=sorted({tag.name for tag in image.tags}),
                    series=image.series.name if image.series is not None else None,
                    characters=sorted({character.name for character in image.characters}),
                    collections=derived_collections,
                    review_status=review[1] if review is not None else "none",
                    rating=max(0.0, min(1.0, review[2] if review is not None else 0.0)),
                    has_duplicate=len(duplicate_statuses) > 0,
                    duplicate_statuses=duplicate_statuses,
                    embedding_vector=self.builder.vector_from_seed(
                        embedding.vector_path if embedding is not None else f"no-embedding:{image.id}"
                    ),
                )
            )

        documents.sort(key=lambda item: item.image_id)
        return documents

    def _passes_filters(self, document: AdvancedSearchDocument, query: AdvancedSearchQuery) -> bool:
        filters = query.filters

        if filters.review_statuses is not None and self.builder.normalize_text(document.review_status) not in filters.review_statuses:
            return False

        if filters.include_duplicates is True and not document.has_duplicate:
            return False
        if filters.include_duplicates is False and document.has_duplicate:
            return False

        if filters.min_rating is not None and document.rating < float(filters.min_rating):
            return False
        if filters.max_rating is not None and document.rating > float(filters.max_rating):
            return False

        if filters.min_width is not None and (document.width is None or document.width < int(filters.min_width)):
            return False
        if filters.max_width is not None and (document.width is None or document.width > int(filters.max_width)):
            return False
        if filters.min_height is not None and (document.height is None or document.height < int(filters.min_height)):
            return False
        if filters.max_height is not None and (document.height is None or document.height > int(filters.max_height)):
            return False

        if filters.file_types is not None and self.builder.normalize_text(document.extension) not in filters.file_types:
            return False

        mime_type = self.builder.normalize_text(document.metadata.get("mime_type"))
        if filters.mime_types is not None and mime_type not in filters.mime_types:
            return False

        effective_date = document.modified_date or document.scan_date or document.created_at
        if filters.date_from is not None and effective_date < filters.date_from:
            return False
        if filters.date_to is not None and effective_date > filters.date_to:
            return False

        folder_norm = self.builder.normalize_text(document.folder)
        if filters.folder_contains and self.builder.normalize_text(filters.folder_contains) not in folder_norm:
            return False

        path_norm = self.builder.normalize_text(document.path)
        if filters.path_contains and self.builder.normalize_text(filters.path_contains) not in path_norm:
            return False

        series_norm = self.builder.normalize_text(document.series)
        if filters.series is not None and series_norm not in filters.series:
            return False

        if filters.characters is not None:
            character_norms = {self.builder.normalize_text(item) for item in document.characters}
            if not character_norms.intersection(filters.characters):
                return False

        if filters.tags is not None:
            tag_norms = {self.builder.normalize_text(item) for item in document.tags}
            if not tag_norms.intersection(filters.tags):
                return False

        if filters.collections is not None:
            collection_norms = {self.builder.normalize_text(item) for item in document.collections}
            if not collection_norms.intersection(filters.collections):
                return False

        return True

    def _weighted_score(
        self,
        *,
        metadata_score: float,
        semantic_score: float,
        tag_score: float,
        recognition_score: float,
        query: AdvancedSearchQuery,
    ) -> float:
        weights = query.weights
        total_weight = (
            weights.metadata_score
            + weights.semantic_score
            + weights.tag_score
            + weights.recognition_score
        )
        weighted = (
            (weights.metadata_score * metadata_score)
            + (weights.semantic_score * semantic_score)
            + (weights.tag_score * tag_score)
            + (weights.recognition_score * recognition_score)
        )
        if total_weight <= 0:
            return 0.0
        return round(max(0.0, min(1.0, weighted / total_weight)), 6)

    def _tag_overlap_score(self, query_tokens: list[str], tags: list[str]) -> float:
        if not query_tokens:
            return 0.0
        if not tags:
            return 0.0
        tag_tokens = {self.builder.normalize_text(tag) for tag in tags}
        overlap = [token for token in query_tokens if token in tag_tokens]
        return float(len(overlap)) / float(len(query_tokens))

    def _recognition_overlap_score(self, query_tokens: list[str], series: str | None, characters: list[str]) -> float:
        if not query_tokens:
            return 0.0
        fields = []
        if series:
            fields.append(series)
        fields.extend(characters)
        if not fields:
            return 0.0

        matched = 0
        for token in query_tokens:
            token_norm = self.builder.normalize_text(token)
            if any(token_norm in self.builder.normalize_text(field) for field in fields):
                matched += 1
        return float(matched) / float(len(query_tokens))

    def _sort_results(
        self,
        items: list[tuple[AdvancedSearchDocument, AdvancedSearchExplanation]],
        query: AdvancedSearchQuery,
    ) -> list[tuple[AdvancedSearchDocument, AdvancedSearchExplanation]]:
        sort_by = query.sort_by if isinstance(query.sort_by, AdvancedSortBy) else AdvancedSortBy(str(query.sort_by))
        direction = query.sort_direction if isinstance(query.sort_direction, AdvancedSortDirection) else AdvancedSortDirection(str(query.sort_direction))

        if sort_by is AdvancedSortBy.SCORE:
            key = lambda row: (row[1].total_score, row[0].image_id)
        elif sort_by is AdvancedSortBy.CREATED_AT:
            key = lambda row: (row[0].created_at, row[0].image_id)
        elif sort_by is AdvancedSortBy.MODIFIED_DATE:
            key = lambda row: (row[0].modified_date or row[0].updated_at, row[0].image_id)
        elif sort_by is AdvancedSortBy.FILENAME:
            key = lambda row: (self.builder.normalize_text(row[0].filename), row[0].image_id)
        elif sort_by is AdvancedSortBy.RATING:
            key = lambda row: (row[0].rating, row[0].image_id)
        elif sort_by is AdvancedSortBy.WIDTH:
            key = lambda row: (row[0].width or 0, row[0].image_id)
        elif sort_by is AdvancedSortBy.HEIGHT:
            key = lambda row: (row[0].height or 0, row[0].image_id)
        else:
            key = lambda row: (row[1].total_score, row[0].image_id)

        reverse = direction is AdvancedSortDirection.DESC
        sorted_items = sorted(items, key=key, reverse=reverse)
        return sorted_items

    def _build_facets(self, documents: list[AdvancedSearchDocument]) -> AdvancedSearchFacets:
        tag_counter = Counter(tag for document in documents for tag in document.tags)
        series_counter = Counter(document.series for document in documents if document.series)
        character_counter = Counter(character for document in documents for character in document.characters)
        file_type_counter = Counter(document.extension for document in documents if document.extension)
        review_counter = Counter(document.review_status for document in documents)
        duplicate_counter = Counter("duplicate" if document.has_duplicate else "unique" for document in documents)

        return AdvancedSearchFacets(
            tags=self._facet_list(tag_counter),
            series=self._facet_list(series_counter),
            characters=self._facet_list(character_counter),
            file_types=self._facet_list(file_type_counter),
            review_statuses=self._facet_list(review_counter),
            duplicate_states=self._facet_list(duplicate_counter),
        )

    def _facet_list(self, counter: Counter[str]) -> list[AdvancedFacetBucket]:
        pairs = sorted(counter.items(), key=lambda item: (-item[1], self.builder.normalize_text(item[0])))
        return [AdvancedFacetBucket(value=str(value), count=int(count)) for value, count in pairs]

    def _build_preview(self, document: AdvancedSearchDocument) -> dict[str, Any]:
        return {
            "series": document.series,
            "characters": list(document.characters),
            "tags": list(document.tags[:5]),
            "resolution": {
                "width": document.width,
                "height": document.height,
            },
            "review_status": document.review_status,
        }

    def _corpus_signature(self, documents: list[AdvancedSearchDocument]) -> str:
        payload = {
            "total": len(documents),
            "ids": [document.image_id for document in documents],
            "updated": [document.updated_at.isoformat() for document in documents],
            "review": [document.review_status for document in documents],
            "duplicates": [document.has_duplicate for document in documents],
        }
        return json.dumps(payload, sort_keys=True)
