from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class ReviewQueueItemRecord(BaseModel):
    """Durable manual-review queue item and its lifecycle state."""

    __tablename__ = "review_queue_item"

    item_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    image_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    proposed_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    current_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reviewer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    series: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    character: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class ReviewBatchRecord(BaseModel):
    """Durable rollback boundary for a group of review decisions."""

    __tablename__ = "review_batch"

    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    review_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class ReviewDecisionRecord(BaseModel):
    """Append-only audit record for a manual-review decision."""

    __tablename__ = "review_decision"

    review_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(64), nullable=False)
    new_status: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)