from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from engine.embeddings.embedding_events import EmbeddingCompleted
from engine.embeddings.embedding_models import EmbeddingCheckpoint, EmbeddingResult
from engine.embeddings.embedding_provider import EmbeddingProvider
from engine.embeddings.embedding_statistics import EmbeddingStatistics
from engine.embeddings.embedding_worker import EmbeddingWorker
from engine.logging import get_logger
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.image_repository import ImageRepository


class EmbeddingEngine:
    """Orchestrates embedding generation for image files.

    The engine generates embedding vectors for images to enable
    visual similarity search and clustering.

    The engine is designed to be called from a pipeline worker that
    consumes jobs from the EMBEDDING queue. It stores results through
    the repository layer and never touches SQLAlchemy directly.

    Crash recovery
    --------------
    If a run is interrupted the caller can pass a :class:`EmbeddingCheckpoint`
    populated with the set of paths that were already processed. On the
    next invocation, those paths are skipped automatically.
    """

    def __init__(
        self,
        *,
        provider: EmbeddingProvider,
        image_repository: ImageRepository | None = None,
        embedding_repository: EmbeddingRepository | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.provider = provider
        self.image_repository = image_repository or ImageRepository()
        self.embedding_repository = embedding_repository or EmbeddingRepository()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.worker = EmbeddingWorker(
            provider=provider,
            image_repository=self.image_repository,
            embedding_repository=self.embedding_repository,
            callback=self._handle_event,
            max_workers=self.max_workers,
        )
        self.statistics = EmbeddingStatistics()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: EmbeddingCheckpoint | None = None,
    ) -> list[EmbeddingResult]:
        """Generate embeddings for all *paths*.

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
        checkpoint: EmbeddingCheckpoint | None = None,
    ) -> EmbeddingResult | None:
        """Generate embedding for a single path."""
        paths = [path]
        results = self.process_paths(paths, checkpoint=checkpoint)
        return results[0] if results else None

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _emit_completion(self) -> None:
        """Emit completion event with statistics."""
        event = EmbeddingCompleted(
            total=self.statistics.processed,
            embedded=self.statistics.embedded,
            skipped=self.statistics.skipped,
            failed=self.statistics.failed,
        )
        self._handle_event(event)

    def _handle_event(self, event: object) -> None:
        """Handle events from the worker."""
        if self.callback is not None:
            self.callback(event)
