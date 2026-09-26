from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class KnowledgeGraphNodeRecord(BaseModel):
    """Persistent materialized node in the library knowledge graph."""

    __tablename__ = "knowledge_graph_node"

    node_id: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True, index=True)
    node_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class KnowledgeGraphEdgeRecord(BaseModel):
    """Persistent relationship between materialized knowledge-graph nodes."""

    __tablename__ = "knowledge_graph_edge"
    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "edge_type", name="uq_knowledge_graph_edge"),
    )

    source_node_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    target_node_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    edge_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}