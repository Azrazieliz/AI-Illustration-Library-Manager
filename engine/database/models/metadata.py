from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.image import Image


class MetadataRecord(BaseModel):
    """Persists extracted image metadata for search and analysis."""

    __tablename__ = "metadata"
    __table_args__ = (
        UniqueConstraint("image_id", name="uq_metadata_image"),
    )

    image_id: Mapped[int] = mapped_column(
        ForeignKey("image.id"), nullable=False, unique=True, index=True
    )
    aspect_ratio: Mapped[float | None] = mapped_column(nullable=True)
    """Width/height ratio of the image."""

    orientation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """EXIF orientation: "normal", "rotated_90", "rotated_180", "rotated_270", "flipped", etc."""

    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """MIME type: "image/jpeg", "image/png", "image/webp", etc."""

    color_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """Pillow color mode: "RGB", "RGBA", "L", "P", "CMYK", etc."""

    bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Bits per pixel or per channel."""

    dpi: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """Dots per inch as "dpi_x,dpi_y" or None if not present."""

    has_icc_profile: Mapped[bool] = mapped_column(default=False, nullable=False)
    """True if image contains embedded ICC color profile."""

    is_animated: Mapped[bool] = mapped_column(default=False, nullable=False)
    """True for animated GIF/WebP."""

    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Number of frames in animation (None if not animated)."""

    exif_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Serialized EXIF metadata as JSON string (subset of useful fields)."""

    image: Mapped["Image"] = relationship(back_populates="metadata_record")
