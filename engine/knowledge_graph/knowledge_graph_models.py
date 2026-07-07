from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class NodeType(str, Enum):
    IMAGE = "image"
    CHARACTER = "character"
    SERIES = "series"
    ARTIST = "artist"
    TAG = "tag"
    EMBEDDING = "embedding"
    DUPLICATE_GROUP = "duplicate_group"


class EdgeType(str, Enum):
    HAS_CHARACTER = "has_character"
    BELONGS_TO_SERIES = "belongs_to_series"
    CREATED_BY_ARTIST = "created_by_artist"
    TAGGED_WITH = "tagged_with"
    HAS_EMBEDDING = "has_embedding"
    IN_DUPLICATE_GROUP = "in_duplicate_group"


@dataclass(slots=True)
class GraphNode:
    id: str
    node_type: NodeType
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source_id: str
    target_id: str
    edge_type: EdgeType
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphPath:
    node_ids: list[str]
    edge_count: int


@dataclass(slots=True)
class GraphTraversalResult:
    start_node_id: str
    visited_node_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgeGraphUpdateResult:
    image_id: int
    path: Path
    created_nodes: int
    created_edges: int
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class KnowledgeGraphCheckpoint:
    processed_paths: set[str] = field(default_factory=set)

    def add_processed(self, path: str | Path) -> None:
        self.processed_paths.add(str(path))

    def is_processed(self, path: str | Path) -> bool:
        return str(path) in self.processed_paths
