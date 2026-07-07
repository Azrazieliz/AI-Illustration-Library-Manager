from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExtractedMetadata:
    """Metadata extracted from a single image file."""

    path: Path
    """Path to the source image."""

    width: int | None = None
    """Image width in pixels."""

    height: int | None = None
    """Image height in pixels."""

    aspect_ratio: float | None = None
    """Width/height ratio."""

    orientation: str | None = None
    """EXIF orientation tag value."""

    mime_type: str | None = None
    """MIME type (e.g., "image/jpeg")."""

    color_mode: str | None = None
    """Pillow color mode (e.g., "RGB", "RGBA", "L")."""

    bit_depth: int | None = None
    """Bits per pixel or per channel."""

    dpi: str | None = None
    """DPI as "x,y" string or None."""

    has_icc_profile: bool = False
    """True if ICC profile is present."""

    is_animated: bool = False
    """True for animated formats."""

    frame_count: int | None = None
    """Number of frames in animation."""

    exif_data: str | None = None
    """JSON-serialized subset of EXIF metadata."""


@dataclass(slots=True)
class MetadataResult:
    """Result from processing a single image through metadata extraction."""

    image_id: int
    """ID of the image record."""

    path: Path
    """Path to the source image."""

    metadata: ExtractedMetadata
    """Extracted metadata."""

    extracted_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """Timestamp when metadata was extracted."""


@dataclass(slots=True)
class MetadataCheckpoint:
    """Crash recovery checkpoint for metadata extraction runs."""

    processed_paths: set[str] = field(default_factory=set)
    """Paths that have been successfully processed."""

    def add_processed(self, path: str | Path) -> None:
        """Record a path as processed."""
        self.processed_paths.add(str(path))

    def is_processed(self, path: str | Path) -> bool:
        """Check if a path has been processed."""
        return str(path) in self.processed_paths
