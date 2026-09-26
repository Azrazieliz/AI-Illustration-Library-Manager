from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class DatasetEntry:
    """Canonical dataset object consumed by future exporters."""

    image_id: int
    path: Path
    payload: dict[str, Any]
    confidence_score: float
    quality_score: float
    completeness_score: float
    provenance: list[str]
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dataset_uuid: str = field(default_factory=lambda: str(uuid4()))
    image_uuid: str | None = None
    caption: str | None = None
    tag_ids: list[str] = field(default_factory=list)
    negative_tags: list[str] = field(default_factory=list)
    character_ids: list[str] = field(default_factory=list)
    series_ids: list[str] = field(default_factory=list)
    artist_ids: list[str] = field(default_factory=list)
    embedding_uuid: str | None = None
    content_hash: str | None = None
    dataset_split: str | None = None
    format: str | None = None


@dataclass(slots=True)
class DatasetBuildResult:
    """Result for one processed source image."""

    image_id: int
    path: Path
    entry: DatasetEntry
    rebuilt: bool = False


@dataclass(slots=True)
class DatasetCheckpoint:
    """Checkpoint for crash recovery and incremental resumption."""

    processed_paths: set[str] = field(default_factory=set)

    def add_processed(self, path: str | Path) -> None:
        self.processed_paths.add(str(path))

    def is_processed(self, path: str | Path) -> bool:
        return str(path) in self.processed_paths
