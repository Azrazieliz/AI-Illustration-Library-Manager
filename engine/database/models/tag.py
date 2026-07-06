from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel
from engine.database.models.image import image_tag_association

if TYPE_CHECKING:
    from engine.database.models.image import Image


class Tag(BaseModel):
    """Represents a tag used to classify images."""

    __tablename__ = "tag"

    name: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    category: Mapped[str | None] = mapped_column(String(256), nullable=True)

    images: Mapped[list["Image"]] = relationship(secondary=image_tag_association, back_populates="tags")
