from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from engine.search.search_exceptions import SearchBackendError
from engine.search.search_models import SearchRecord


@dataclass(slots=True)
class BackendResult:
    """Raw backend match with score and lookup key."""

    image_id: int
    similarity: float


class SearchBackend(ABC):
    """Abstract backend contract for vector index implementations."""

    @abstractmethod
    def upsert(self, record: SearchRecord) -> None:
        """Insert or update one record."""

    @abstractmethod
    def query(
        self,
        *,
        vector: list[float],
        top_k: int,
        min_similarity: float,
    ) -> list[BackendResult]:
        """Return nearest neighbors sorted by descending similarity."""

    @abstractmethod
    def size(self) -> int:
        """Return number of indexed vectors."""


class InMemorySearchBackend(SearchBackend):
    """Default in-memory cosine-similarity backend for testing and local runs."""

    def __init__(self) -> None:
        self._vectors: dict[int, list[float]] = {}

    def upsert(self, record: SearchRecord) -> None:
        self._vectors[record.image_id] = list(record.vector)

    def query(
        self,
        *,
        vector: list[float],
        top_k: int,
        min_similarity: float,
    ) -> list[BackendResult]:
        if top_k <= 0:
            return []

        query_norm = _vector_norm(vector)
        if query_norm == 0.0:
            raise SearchBackendError("Query vector has zero magnitude")

        scored: list[BackendResult] = []
        for image_id, candidate in self._vectors.items():
            similarity = _cosine_similarity(vector, query_norm, candidate)
            if similarity >= min_similarity:
                scored.append(BackendResult(image_id=image_id, similarity=similarity))

        scored.sort(key=lambda item: item.similarity, reverse=True)
        return scored[:top_k]

    def size(self) -> int:
        return len(self._vectors)


def _vector_norm(vector: list[float]) -> float:
    total = 0.0
    for value in vector:
        total += value * value
    return total ** 0.5


def _cosine_similarity(query: list[float], query_norm: float, candidate: list[float]) -> float:
    if len(query) != len(candidate):
        raise SearchBackendError("Vector dimension mismatch")

    candidate_norm = _vector_norm(candidate)
    if candidate_norm == 0.0:
        return 0.0

    dot = 0.0
    for left, right in zip(query, candidate):
        dot += left * right

    return dot / (query_norm * candidate_norm)
