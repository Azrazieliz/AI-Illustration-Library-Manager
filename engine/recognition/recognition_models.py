from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class RecognitionLabel:
    """A single recognized label and confidence score."""

    name: str
    confidence: float


@dataclass(slots=True)
class RecognitionOutput:
    """Recognition output for one image."""

    series: RecognitionLabel | None = None
    characters: list[RecognitionLabel] = field(default_factory=list)
    provider_name: str = "unknown"
    model_name: str = "unknown"
    model_version: str = "1.0.0"


@dataclass(slots=True)
class RecognitionResult:
    """Persisted recognition result for one image path."""

    image_id: int
    path: Path
    output: RecognitionOutput
    recognized_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class RecognitionCheckpoint:
    """Crash recovery checkpoint for recognition runs."""

    processed_paths: set[str] = field(default_factory=set)

    def add_processed(self, path: str | Path) -> None:
        """Mark a path as processed."""
        self.processed_paths.add(str(path))

    def is_processed(self, path: str | Path) -> bool:
        """Return True when *path* is already processed."""
        return str(path) in self.processed_paths
