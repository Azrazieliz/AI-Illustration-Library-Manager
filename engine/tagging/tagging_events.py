from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TaggingStarted:
    path: Path


@dataclass(slots=True)
class TaggingGenerated:
    path: Path
    image_id: int
    tag_count: int


@dataclass(slots=True)
class TaggingSkipped:
    path: Path
    reason: str


@dataclass(slots=True)
class TaggingFailed:
    path: Path
    error: str


@dataclass(slots=True)
class TaggingCompleted:
    total: int
    tagged: int
    skipped: int
    failed: int
