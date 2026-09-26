from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.image import Image


class Embedding(BaseModel):
    """Stores the embedding artifact reference for an image."""

    __tablename__ = "embedding"

    image_id: Mapped[int] = mapped_column(ForeignKey("image.id"), nullable=False, unique=True)
    vector_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    model_name: Mapped[str] = mapped_column(String(512), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    image_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dtype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    image: Mapped["Image"] = relationship(back_populates="embedding")

    __mapper_args__ = {"version_id_col": version}

    @property
    def embedding_uuid(self) -> str:
        return self.uuid
