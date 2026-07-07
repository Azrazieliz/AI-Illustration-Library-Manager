from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class KnowledgeGraphBuildStarted:
    path: Path


@dataclass(slots=True)
class KnowledgeGraphUpdated:
    path: Path
    image_id: int
    created_nodes: int
    created_edges: int


@dataclass(slots=True)
class KnowledgeGraphBuildSkipped:
    path: Path
    reason: str


@dataclass(slots=True)
class KnowledgeGraphBuildFailed:
    path: Path
    error: str


@dataclass(slots=True)
class KnowledgeGraphBatchCompleted:
    total: int
    updated: int
    skipped: int
    failed: int
