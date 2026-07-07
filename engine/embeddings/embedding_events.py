from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class EmbeddingStarted:
    """Raised when embedding generation begins for a file."""

    path: Path
    model_name: str


@dataclass(slots=True)
class EmbeddingExtracted:
    """Raised when embedding extraction succeeds for a file."""

    path: Path
    dimensions: int
    model_name: str


@dataclass(slots=True)
class EmbeddingSkipped:
    """Raised when embedding generation is skipped for a file."""

    path: Path
    reason: str


@dataclass(slots=True)
class EmbeddingFailed:
    """Raised when embedding generation fails for a file."""

    path: Path
    error: str


@dataclass(slots=True)
class EmbeddingCompleted:
    """Raised when a batch embedding generation run finishes."""

    total: int
    embedded: int
    skipped: int
    failed: int
