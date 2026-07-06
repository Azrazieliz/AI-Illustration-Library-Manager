from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.image import Image


class Review(BaseModel):
    """Represents a review or moderation entry for an image."""

    __tablename__ = "review"

    image_id: Mapped[int] = mapped_column(ForeignKey("image.id"), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Integer, nullable=True)
    series_confidence: Mapped[float | None] = mapped_column(Integer, nullable=True)
    character_confidence: Mapped[float | None] = mapped_column(Integer, nullable=True)
    tag_confidence: Mapped[float | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")

    image: Mapped["Image"] = relationship(back_populates="reviews")
