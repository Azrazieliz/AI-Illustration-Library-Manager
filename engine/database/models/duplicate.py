from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.image import Image


class DuplicateRecord(BaseModel):
    """Persists a detected duplicate relationship between two images."""

    __tablename__ = "duplicate"
    __table_args__ = (
        # Prevent storing the same pair twice regardless of ordering
        UniqueConstraint("image_a_id", "image_b_id", name="uq_duplicate_pair"),
    )

    image_a_id: Mapped[int] = mapped_column(
        ForeignKey("image.id"), nullable=False, index=True
    )
    image_b_id: Mapped[int] = mapped_column(
        ForeignKey("image.id"), nullable=False, index=True
    )
    match_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "exact" | "perceptual"
    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # "high" | "medium" | "low"
    sha256_match: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phash_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ahash_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dhash_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # "pending" | "reviewed" | "rejected"

    image_a: Mapped["Image"] = relationship(foreign_keys=[image_a_id])
    image_b: Mapped["Image"] = relationship(foreign_keys=[image_b_id])
