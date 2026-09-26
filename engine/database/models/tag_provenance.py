from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class TagProvenance(BaseModel):
    """Immutable evidence record for one generated image-tag relationship."""

    __tablename__ = "tag_provenance"

    image_uuid: Mapped[str] = mapped_column(String(36), ForeignKey("image.uuid"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_uuid: Mapped[str | None] = mapped_column(String(36), ForeignKey("review.uuid"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}

    @property
    def provenance_uuid(self) -> str:
        return self.uuid