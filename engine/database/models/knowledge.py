from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class Knowledge(BaseModel):
    """Represents a knowledge artifact or snapshot."""

    __tablename__ = "knowledge"

    version: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(512), nullable=True)
