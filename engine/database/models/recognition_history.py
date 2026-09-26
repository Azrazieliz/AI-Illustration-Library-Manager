from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class RecognitionHistory(BaseModel):
    """Append-only record of one recognition result for an image."""

    __tablename__ = "recognition_history"

    image_uuid: Mapped[str] = mapped_column(String(36), ForeignKey("image.uuid"), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    selected_candidate: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    runtime: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}

    @property
    def recognition_uuid(self) -> str:
        return self.uuid