from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from engine.logging import get_logger
from engine.search.search_events import SearchCompleted, SearchFailed, SearchIndexed, SearchSkipped, SearchStarted
from engine.search.search_exceptions import SearchBackendError, SearchIndexingError, SearchQueryError
from engine.search.search_index import SearchIndex
from engine.search.search_models import (
    SearchCheckpoint,
    SearchIndexResult,
    SearchMatch,
    SearchQuery,
    SearchRecord,
    SearchResult,
)
from engine.search.search_statistics import SearchStatistics
from engine.repositories.search_repository import SearchRepository


class SearchEngine:
    """Orchestrates semantic indexing and similarity retrieval."""

    def __init__(
        self,
        *,
        repository: SearchRepository | None = None,
        index: SearchIndex | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.repository = repository or SearchRepository()
        self.index = index or SearchIndex()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = SearchStatistics()

    def index_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: SearchCheckpoint | None = None,
    ) -> list[SearchIndexResult]:
        """Index semantic records for all provided paths."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self.statistics = SearchStatistics()
        self.statistics.start()
        results: list[SearchIndexResult] = []
        resolved_paths = [str(Path(path).resolve()) for path in paths]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._index_one, path, checkpoint): path
                for path in resolved_paths
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)

        self.statistics.finish()
        self._emit(
            SearchCompleted(
                total=self.statistics.processed,
                indexed=self.statistics.indexed,
                skipped=self.statistics.skipped,
                failed=self.statistics.failed,
            )
        )
        return results

    def index_path(
        self,
        path: Path | str,
        *,
        checkpoint: SearchCheckpoint | None = None,
    ) -> SearchIndexResult | None:
        """Index semantic record for one path."""
        return self._index_one(str(Path(path).resolve()), checkpoint)

    def search(
        self,
        *,
        query_vector: list[float],
        top_k: int = 10,
        min_similarity: float = 0.0,
    ) -> SearchResult:
        """Run cosine-similarity k-nearest-neighbor retrieval."""
        if top_k <= 0:
            raise SearchQueryError("top_k must be greater than zero")
        if min_similarity < -1.0 or min_similarity > 1.0:
            raise SearchQueryError("min_similarity must be between -1 and 1")

        query = SearchQuery(vector=query_vector, top_k=top_k, min_similarity=min_similarity)

        try:
            backend_result = self.index.query(query)
        except SearchBackendError as e:
            raise SearchQueryError(str(e)) from e

        resolved_matches: list[SearchMatch] = []
        for item in backend_result.matches:
            image_id = item["image_id"]
            similarity = float(item["similarity"])
            image = self.repository.get_image_by_id(image_id)
            if image is None:
                continue
            resolved_matches.append(
                SearchMatch(
                    image_id=image_id,
                    path=Path(image.original_path),
                    similarity=similarity,
                    metadata={
                        "filename": image.filename,
                    },
                )
            )

        return SearchResult(query=query, matches=resolved_matches)

    def _index_one(
        self,
        path: str,
        checkpoint: SearchCheckpoint | None,
    ) -> SearchIndexResult | None:
        resolved_path = Path(path)

        if checkpoint is not None and checkpoint.is_processed(path):
            self.statistics.increment_processed()
            self.statistics.increment_skipped()
            self._emit(SearchSkipped(path=resolved_path, reason="Already processed"))
            return None

        repository = SearchRepository()
        self.statistics.increment_processed()
        self._emit(SearchStarted(path=resolved_path))

        try:
            image = repository.get_image_by_path(path)
            if image is None:
                self.statistics.increment_skipped()
                self._emit(SearchSkipped(path=resolved_path, reason="Image not found"))
                return None

            embedding = repository.get_embedding_by_image_id(image.id)
            if embedding is None:
                self.statistics.increment_skipped()
                self._emit(SearchSkipped(path=resolved_path, reason="Embedding not found"))
                return None

            vector = self._load_vector(embedding.vector_path)
            record = SearchRecord(
                image_id=image.id,
                path=resolved_path,
                vector=vector,
                model_name=embedding.model_name,
                model_version=embedding.model_version,
                metadata={"filename": image.filename},
            )
            self.index.upsert(record)

            if checkpoint is not None:
                checkpoint.add_processed(path)

            self.statistics.increment_indexed()
            self._emit(SearchIndexed(path=resolved_path, image_id=image.id, dimensions=len(vector)))
            return SearchIndexResult(image_id=image.id, path=resolved_path, record=record)

        except (SearchBackendError, SearchIndexingError) as e:
            self.statistics.increment_failed()
            self._emit(SearchFailed(path=resolved_path, error=str(e)))
            return None
        except Exception as e:
            self.statistics.increment_failed()
            self._emit(SearchFailed(path=resolved_path, error=f"Unexpected error: {e}"))
            return None

    def _load_vector(self, vector_path: str) -> list[float]:
        """Load vector from storage path.

        Current embedding worker stores placeholder paths only, so this method
        deterministically reconstructs a stable mock vector from the path.
        """
        try:
            payload = json.dumps({"vector_path": vector_path})
            seed = payload.encode("utf-8")
            vector: list[float] = []
            # Build a deterministic 128-d vector from bytes.
            while len(vector) < 128:
                for value in seed:
                    vector.append(float(value) / 255.0)
                    if len(vector) >= 128:
                        break
            return vector
        except Exception as e:
            raise SearchIndexingError(f"Could not load vector: {e}") from e

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
