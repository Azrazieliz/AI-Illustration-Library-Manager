from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class ExportArtifactRecord(BaseModel):
    """Durable export output and its audit metadata for one image/format pair."""

    __tablename__ = "export_artifact"
    __table_args__ = (UniqueConstraint("format_type", "image_id", name="uq_export_artifact_format_image"),)

    format_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    image_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}