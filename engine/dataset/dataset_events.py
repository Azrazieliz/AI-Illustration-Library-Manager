from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DatasetStarted:
    path: Path


@dataclass(slots=True)
class DatasetBuilt:
    path: Path
    image_id: int
    rebuilt: bool


@dataclass(slots=True)
class DatasetSkipped:
    path: Path
    reason: str


@dataclass(slots=True)
class DatasetFailed:
    path: Path
    error: str


@dataclass(slots=True)
class DatasetCompleted:
    total: int
    built: int
    skipped: int
    failed: int
