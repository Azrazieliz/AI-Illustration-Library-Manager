from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass(slots=True)
class ScannerStatistics:
    """Tracks summary metrics for a scanner run."""

    folders_scanned: int = 0
    files_scanned: int = 0
    images_detected: int = 0
    new_files: int = 0
    updated_files: int = 0
    deleted_files: int = 0
    ignored_files: int = 0
    errors: int = 0
    elapsed_time: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        """Mark the start of a scan run."""
        self.started_at = perf_counter()

    def complete(self) -> None:
        """Mark the completion of a scan run."""
        if self.started_at is not None:
            self.completed_at = perf_counter()
            self.elapsed_time = self.completed_at - self.started_at
