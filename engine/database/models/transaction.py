from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.image import Image


class Transaction(BaseModel):
    """Tracks filesystem or state change transactions."""

    __tablename__ = "transaction"

    image_id: Mapped[int | None] = mapped_column(ForeignKey("image.id"), nullable=True)
    operation: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    old_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    new_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    rollback_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    image: Mapped["Image | None"] = relationship(back_populates="transactions")
