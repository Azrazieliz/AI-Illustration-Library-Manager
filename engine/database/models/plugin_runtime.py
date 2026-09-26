from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class PluginRuntimeRecord(BaseModel):
    """Durable plugin manifest and user-managed runtime configuration."""

    __tablename__ = "plugin_runtime"

    plugin_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    manifest_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="registered", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    health_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    subscriptions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    scheduled_tasks: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}