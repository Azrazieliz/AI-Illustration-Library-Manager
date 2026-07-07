from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.image import Image


class HashModel(BaseModel):
    """Stores hash values associated with an image."""

    __tablename__ = "hash"

    image_id: Mapped[int] = mapped_column(ForeignKey("image.id"), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    phash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ahash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dhash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    image: Mapped["Image"] = relationship(back_populates="hash_record")
