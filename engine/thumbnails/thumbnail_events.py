from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ThumbnailStarted:
    """Raised when the engine begins processing an image."""

    source_path: str


@dataclass(slots=True)
class ThumbnailGenerated:
    """Raised when all thumbnail variants for an image have been generated."""

    source_path: str
    sizes: list[int]
    file_paths: list[str]


@dataclass(slots=True)
class ThumbnailCacheHit:
    """Raised when all thumbnails for an image were served from the cache."""

    source_path: str
    sizes: list[int]


@dataclass(slots=True)
class ThumbnailFailed:
    """Raised when thumbnail generation fails for an image."""

    source_path: str
    error: str


@dataclass(slots=True)
class ThumbnailCompleted:
    """Raised when a thumbnail generation run finishes."""

    total: int
    generated: int
    cached: int
    failed: int
