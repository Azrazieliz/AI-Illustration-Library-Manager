from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class CollectionRecordRow(BaseModel):
    """Durable collection header, hierarchy, and presentation state."""

    __tablename__ = "collection"

    name: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    smart_rule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    thumbnail_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class CollectionMembershipRecord(BaseModel):
    """Durable image membership for a collection without referential enforcement."""

    __tablename__ = "collection_membership"
    __table_args__ = (UniqueConstraint("collection_id", "image_id", name="uq_collection_membership_collection_image"),)

    collection_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    image_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)