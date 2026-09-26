from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from engine.repositories.search_repository import SearchRepository
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


class RepositorySearchBackend(SearchBackend):
    """Query durable NumPy embedding artifacts referenced by SQLite records."""

    def __init__(self, repository: SearchRepository | None = None) -> None:
        self.repository = repository

    def upsert(self, record: SearchRecord) -> None:
        repository = SearchRepository()
        embedding = repository.get_embedding_by_image_id(record.image_id)
        if embedding is None:
            raise SearchBackendError(f"Cannot index image {record.image_id}: embedding record is missing")
        if Path(embedding.vector_path) != Path(record.metadata.get("vector_path", embedding.vector_path)):
            raise SearchBackendError(f"Cannot index image {record.image_id}: embedding artifact changed during indexing")

    def query(
        self,
        *,
        vector: list[float],
        top_k: int,
        min_similarity: float,
    ) -> list[BackendResult]:
        if top_k <= 0:
            return []
        query = _normalized_vector(vector, "query")
        candidate_ids: list[int] = []
        candidates: list[np.ndarray] = []
        repository = SearchRepository()
        for embedding in repository.list_embeddings():
            candidate = _load_vector(Path(embedding.vector_path), image_id=embedding.image_id)
            if candidate.size != query.size:
                continue
            candidate_ids.append(embedding.image_id)
            candidates.append(candidate)
        if not candidates:
            return []

        matrix = np.ascontiguousarray(np.vstack(candidates), dtype=np.float32)
        index = faiss.IndexFlatIP(query.size)
        index.add(matrix)
        scores, positions = index.search(query.reshape(1, -1), min(top_k, len(candidate_ids)))
        return [
            BackendResult(image_id=candidate_ids[position], similarity=float(score))
            for score, position in zip(scores[0], positions[0])
            if position >= 0 and float(score) >= min_similarity
        ]

    def size(self) -> int:
        repository = SearchRepository()
        return len(repository.list_embeddings())


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


def _load_vector(path: Path, *, image_id: int) -> np.ndarray:
    if not path.is_file():
        raise SearchBackendError(f"Embedding artifact is missing for image {image_id}: {path}")
    try:
        vector = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise SearchBackendError(f"Embedding artifact is unreadable for image {image_id}: {path}") from exc
    return _normalized_vector(vector, f"image {image_id}")


def _normalized_vector(values: list[float] | np.ndarray, label: str) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.isfinite(vector).all():
        raise SearchBackendError(f"Embedding vector for {label} is empty or non-finite")
    magnitude = float(np.linalg.norm(vector))
    if magnitude == 0.0:
        raise SearchBackendError(f"Embedding vector for {label} has zero magnitude")
    return vector / magnitude
