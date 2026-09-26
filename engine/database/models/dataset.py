from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class DatasetRecord(BaseModel):
    """Versioned dataset entry that references canonical Fusion entities by UUID."""

    __tablename__ = "dataset"

    image_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    tag_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    negative_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    character_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    series_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    artist_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    embedding_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    dataset_split: Mapped[str | None] = mapped_column(String(64), nullable=True)
    format: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    completeness_score: Mapped[float] = mapped_column(Float, nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}

    @property
    def dataset_uuid(self) -> str:
        return self.uuid