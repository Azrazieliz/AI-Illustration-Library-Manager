from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class KnowledgePackStateRecord(BaseModel):
    """Versioned installed-pack and rollback state for external knowledge packs."""

    __tablename__ = "knowledge_pack_state"

    state_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    state_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}