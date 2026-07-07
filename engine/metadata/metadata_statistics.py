from __future__ import annotations

from dataclasses import dataclass, field
from time import time


@dataclass(slots=True)
class MetadataStatistics:
    """Tracks statistics for a metadata extraction run."""

    processed: int = 0
    """Number of files processed."""

    extracted: int = 0
    """Number of files with metadata successfully extracted."""

    unsupported: int = 0
    """Number of files with unsupported format."""

    corrupted: int = 0
    """Number of files that are corrupted or unreadable."""

    failed: int = 0
    """Number of files where extraction failed for other reasons."""

    elapsed_seconds: float = 0.0
    """Total elapsed time in seconds."""

    _start_time: float = field(default=0.0, init=False)

    def start(self) -> None:
        """Mark the start of a run."""
        self._start_time = time()

    def finish(self) -> None:
        """Mark the end of a run and compute elapsed time."""
        if self._start_time > 0:
            self.elapsed_seconds = time() - self._start_time

    def __str__(self) -> str:
        """Return human-readable statistics."""
        return (
            f"Metadata(processed={self.processed}, extracted={self.extracted}, "
            f"unsupported={self.unsupported}, corrupted={self.corrupted}, "
            f"failed={self.failed}, elapsed={self.elapsed_seconds:.2f}s)"
        )
