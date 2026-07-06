from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class Job(BaseModel):
    """Representation of an asynchronous background job."""

    __tablename__ = "job"

    type: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
