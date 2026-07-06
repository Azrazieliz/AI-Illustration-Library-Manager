from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from typing import Iterable

from engine.indexer.indexer import IncrementalIndexer
from engine.indexer.indexer_models import IndexerCheckpoint
from engine.pipeline import QueueManager


class IndexerWorker:
    """Background worker for incremental indexing."""

    def __init__(self, *, queue_manager: QueueManager | None = None, indexer: IncrementalIndexer | None = None) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.indexer = indexer or IncrementalIndexer()
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self, roots: Iterable[Path | str]) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, args=(list(roots),), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self, roots: list[Path | str]) -> None:
        checkpoint = IndexerCheckpoint(root=str(Path(roots[0]).resolve()) if roots else "")
        self.indexer.index_paths(roots, checkpoint=checkpoint)
