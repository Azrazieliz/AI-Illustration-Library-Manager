from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class AdvancedSavedSearchRecord(BaseModel):
    """Durable user-defined advanced-search query."""

    __tablename__ = "advanced_saved_search"

    search_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    query_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class AdvancedSearchHistoryRecord(BaseModel):
    """Append-only advanced-search execution history."""

    __tablename__ = "advanced_search_history"

    query_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)