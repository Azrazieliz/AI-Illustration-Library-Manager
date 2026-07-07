from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ThumbnailSize(int, Enum):
    """Standard thumbnail sizes (longest-edge pixels)."""

    SMALL = 128
    MEDIUM = 256
    LARGE = 512


class ThumbnailFormat(str, Enum):
    """Supported thumbnail output formats."""

    WEBP = "webp"
    JPEG = "jpeg"
    PNG = "png"


@dataclass(slots=True)
class ThumbnailSpec:
    """Specification for a single thumbnail variant."""

    size: int
    """Longest-edge target in pixels.  The image is never upscaled."""

    format: ThumbnailFormat = ThumbnailFormat.WEBP

    quality: int = 85
    """Compression quality (1–95) for lossy formats."""

    def extension(self) -> str:
        return self.format.value


# Platform-optimised preview profiles defined after ThumbnailSpec
PREVIEW_PROFILES: dict[str, ThumbnailSpec] = {
    "flutter": ThumbnailSpec(size=512, format=ThumbnailFormat.WEBP),
    "android": ThumbnailSpec(size=512, format=ThumbnailFormat.WEBP, quality=80),
    "desktop": ThumbnailSpec(size=512, format=ThumbnailFormat.PNG),
}

# Default sizes generated for every image
DEFAULT_SIZES: list[int] = [
    ThumbnailSize.SMALL,
    ThumbnailSize.MEDIUM,
    ThumbnailSize.LARGE,
]


@dataclass(slots=True)
class GeneratedThumbnail:
    """Metadata for a single successfully generated thumbnail file."""

    spec: ThumbnailSpec
    file_path: Path
    width: int
    height: int
    file_size_bytes: int
    cache_key: str


@dataclass(slots=True)
class ThumbnailResult:
    """Result of processing all thumbnail variants for one source image."""

    source_path: str
    image_id: int
    thumbnails: list[GeneratedThumbnail]
    from_cache: bool
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThumbnailCheckpoint:
    """Crash-recovery state for an interrupted thumbnail generation run."""

    processed_paths: set[str] = field(default_factory=set)
    completed: bool = False

