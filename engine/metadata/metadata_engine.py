from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from engine.logging import get_logger
from engine.metadata.metadata_events import MetadataCompleted
from engine.metadata.metadata_models import MetadataCheckpoint, MetadataResult
from engine.metadata.metadata_statistics import MetadataStatistics
from engine.metadata.metadata_worker import MetadataWorker
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository


class MetadataEngine:
    """Orchestrates metadata extraction for image files.

    The engine extracts image dimensions, color information, EXIF data,
    animation properties, and other metadata that enables search and
    categorization.

    The engine is designed to be called from a pipeline worker that
    consumes jobs from the METADATA queue. It stores results through
    the repository layer and never touches SQLAlchemy directly.

    Crash recovery
    --------------
    If a run is interrupted the caller can pass a :class:`MetadataCheckpoint`
    populated with the set of paths that were already processed.  On the
    next invocation, those paths are skipped automatically.
    """

    def __init__(
        self,
        *,
        image_repository: ImageRepository | None = None,
        metadata_repository: MetadataRepository | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.image_repository = image_repository or ImageRepository()
        self.metadata_repository = metadata_repository or MetadataRepository()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.worker = MetadataWorker(
            image_repository=self.image_repository,
            metadata_repository=self.metadata_repository,
            callback=self._handle_event,
            max_workers=self.max_workers,
        )
        self.statistics = MetadataStatistics()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: MetadataCheckpoint | None = None,
    ) -> list[MetadataResult]:
        """Extract metadata for all *paths*.

        Files that are skipped (checkpoint) are not included in the returned
        list but are counted in ``statistics.processed``.
        """
        results = self.worker.process_paths(paths, checkpoint=checkpoint)
        self.statistics = self.worker.statistics
        self._emit_completion()
        return results

    def process_path(
        self,
        path: Path | str,
        *,
        checkpoint: MetadataCheckpoint | None = None,
    ) -> MetadataResult | None:
        """Extract metadata for a single path."""
        return self.worker.process_path(path, checkpoint=checkpoint)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _handle_event(self, event: object) -> None:
        """Handle events from the worker."""
        self._emit(event)

    def _emit_completion(self) -> None:
        """Emit completion event with final statistics."""
        self._emit(
            MetadataCompleted(
                total=self.statistics.processed,
                extracted=self.statistics.extracted,
                unsupported=self.statistics.unsupported,
                corrupted=self.statistics.corrupted,
                failed=self.statistics.failed,
            )
        )

    def _emit(self, event: object) -> None:
        """Emit an event to registered listeners."""
        if self.callback is not None:
            self.callback(event)
