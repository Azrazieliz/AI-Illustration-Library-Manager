from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class TagKind(str, Enum):
    SUGGESTED = "suggested"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"


@dataclass(slots=True)
class GeneratedTag:
    name: str
    confidence: float
    kind: TagKind
    provenance: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaggingContext:
    image_id: int
    path: Path
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    recognition: dict[str, object] = field(default_factory=dict)
    semantic_neighbors: list[dict[str, object]] = field(default_factory=list)
    graph_neighbors: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class TaggingResult:
    image_id: int
    path: Path
    generated_tags: list[GeneratedTag] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class TaggingCheckpoint:
    processed_paths: set[str] = field(default_factory=set)

    def add_processed(self, path: str | Path) -> None:
        self.processed_paths.add(str(path))

    def is_processed(self, path: str | Path) -> bool:
        return str(path) in self.processed_paths
