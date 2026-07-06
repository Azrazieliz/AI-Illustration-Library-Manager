from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class IndexDecision(str, Enum):
    """Classification of a discovered file during incremental indexing."""

    NEW = "new"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


class IndexStatus(str, Enum):
    """Indexer lifecycle status."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(slots=True)
class IndexState:
    """Tracked state for an indexed file."""

    path: str
    size: int | None = None
    mtime: datetime | None = None
    filename: str | None = None
    extension: str | None = None
    created_at: datetime | None = None
    last_seen: datetime | None = None


@dataclass(slots=True)
class IndexRecord:
    """Representation of an indexed file record."""

    source_path: str
    filename: str
    extension: str | None
    size: int | None
    mtime: datetime | None
    created_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)
    decision: IndexDecision = IndexDecision.NEW
    indexed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class IndexerCheckpoint:
    """Minimal checkpoint used to resume indexing safely."""

    root: str
    processed_paths: set[str] = field(default_factory=set)
    completed: bool = False
