from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.image import Image


class ThumbnailRecord(BaseModel):
    """Persists metadata for a generated thumbnail."""

    __tablename__ = "thumbnail"
    __table_args__ = (
        # One record per (image, size) pair
        UniqueConstraint("image_id", "size", name="uq_thumbnail_image_size"),
    )

    image_id: Mapped[int] = mapped_column(
        ForeignKey("image.id"), nullable=False, index=True
    )
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    """Longest-edge target size used during generation."""

    format: Mapped[str] = mapped_column(String(8), nullable=False)
    """File format: "webp" or "jpeg"."""

    file_path: Mapped[str] = mapped_column(String(4096), nullable=False)
    """Absolute path to the thumbnail file on disk."""

    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    """Size of the thumbnail file in bytes."""

    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    """Content-addressable key derived from source path + file size + mtime."""

    thumb_width: Mapped[int] = mapped_column(Integer, nullable=False)
    thumb_height: Mapped[int] = mapped_column(Integer, nullable=False)

    image: Mapped["Image"] = relationship(foreign_keys=[image_id])
