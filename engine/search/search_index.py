from __future__ import annotations

from engine.search.search_backend import InMemorySearchBackend, SearchBackend
from engine.search.search_models import SearchRecord, SearchResult, SearchQuery


class SearchIndex:
    """Backend-agnostic index facade for semantic vector search."""

    def __init__(self, backend: SearchBackend | None = None) -> None:
        self.backend = backend or InMemorySearchBackend()

    def upsert(self, record: SearchRecord) -> None:
        """Insert or update one searchable vector record."""
        self.backend.upsert(record)

    def query(self, query: SearchQuery) -> SearchResult:
        """Run k-nearest-neighbor query with cosine similarity threshold."""
        raw = self.backend.query(
            vector=query.vector,
            top_k=query.top_k,
            min_similarity=query.min_similarity,
        )

        matches = []
        for item in raw:
            matches.append(
                {
                    "image_id": item.image_id,
                    "similarity": item.similarity,
                }
            )

        # SearchEngine maps ids back to full metadata/path records.
        return SearchResult(query=query, matches=matches)  # type: ignore[arg-type]
