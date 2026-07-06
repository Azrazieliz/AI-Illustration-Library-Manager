from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel
from engine.database.models.image import image_character_association

if TYPE_CHECKING:
    from engine.database.models.image import Image
    from engine.database.models.series import Series


class Character(BaseModel):
    """Represents an identifiable character."""

    __tablename__ = "character"

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases: Mapped[str | None] = mapped_column(Text, nullable=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id"), nullable=True)

    series: Mapped["Series | None"] = relationship(back_populates="characters")
    images: Mapped[list["Image"]] = relationship(secondary=image_character_association, back_populates="characters")
