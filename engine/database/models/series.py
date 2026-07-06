from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.character import Character
    from engine.database.models.image import Image


class Series(BaseModel):
    """Represents a visual series or collection."""

    __tablename__ = "series"

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases: Mapped[str | None] = mapped_column(Text, nullable=True)

    images: Mapped[list["Image"]] = relationship(back_populates="series")
    characters: Mapped[list["Character"]] = relationship(back_populates="series")
