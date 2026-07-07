from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class ExtractedEmbedding:
    """Represents extracted embedding data from an image."""

    image_id: int
    embedding_vector: list[float]
    model_name: str
    model_version: str
    dimensions: int
    provider_name: str


@dataclass(slots=True)
class EmbeddingResult:
    """Result of embedding generation for a single image."""

    image_id: int
    path: Path
    embedding: ExtractedEmbedding
    extracted_at: datetime


@dataclass(slots=True)
class EmbeddingCheckpoint:
    """Tracks processed images for crash recovery."""

    processed_paths: set[str] = field(default_factory=set)

    def add_processed(self, path: str | Path) -> None:
        """Mark a path as processed."""
        self.processed_paths.add(str(path))

    def is_processed(self, path: str | Path) -> bool:
        """Check if a path has been processed."""
        return str(path) in self.processed_paths
