from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SearchRecord:
    """A semantic vector record stored in the search index."""

    image_id: int
    path: Path
    vector: list[float]
    model_name: str
    model_version: str
    metadata: dict[str, Any] = field(default_factory=dict)
    indexed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class SearchMatch:
    """Single nearest-neighbor match for a search query."""

    image_id: int
    path: Path
    similarity: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchQuery:
    """Search query descriptor with retrieval controls."""

    vector: list[float]
    top_k: int = 10
    min_similarity: float = 0.0


@dataclass(slots=True)
class SearchResult:
    """Result payload for a vector similarity query."""

    query: SearchQuery
    matches: list[SearchMatch] = field(default_factory=list)


@dataclass(slots=True)
class SearchIndexResult:
    """Result from indexing a single image into semantic search."""

    image_id: int
    path: Path
    record: SearchRecord
    indexed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class SearchCheckpoint:
    """Crash recovery checkpoint for semantic search indexing runs."""

    processed_paths: set[str] = field(default_factory=set)

    def add_processed(self, path: str | Path) -> None:
        """Record path as processed."""
        self.processed_paths.add(str(path))

    def is_processed(self, path: str | Path) -> bool:
        """Check if path has been processed."""
        return str(path) in self.processed_paths
