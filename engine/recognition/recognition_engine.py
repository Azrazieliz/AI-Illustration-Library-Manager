from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from engine.logging import get_logger
from engine.recognition.recognition_events import RecognitionCompleted
from engine.recognition.recognition_models import (
    RecognitionAggregation,
    RecognitionCheckpoint,
    RecognitionResult,
    aggregate_recognition_results,
)
from engine.recognition.recognition_provider import RecognitionProvider
from engine.recognition.recognition_statistics import RecognitionStatistics
from engine.recognition.recognition_worker import RecognitionWorker
from engine.repositories.recognition_repository import RecognitionRepository


class RecognitionEngine:
    """Orchestrates recognition generation and persistence."""

    def __init__(
        self,
        *,
        provider: RecognitionProvider,
        recognition_repository: RecognitionRepository | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.provider = provider
        self.recognition_repository = recognition_repository or RecognitionRepository()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.worker = RecognitionWorker(
            provider=provider,
            recognition_repository=self.recognition_repository,
            callback=self._handle_event,
            max_workers=self.max_workers,
        )
        self.statistics = RecognitionStatistics()
        self.last_aggregation = RecognitionAggregation()

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: RecognitionCheckpoint | None = None,
    ) -> list[RecognitionResult]:
        """Run recognition for all provided paths."""
        results = self.worker.process_paths(paths, checkpoint=checkpoint)
        self.statistics = self.worker.statistics
        self.last_aggregation = aggregate_recognition_results(results)
        self._emit_completion()
        return results

    def process_path(
        self,
        path: Path | str,
        *,
        checkpoint: RecognitionCheckpoint | None = None,
    ) -> RecognitionResult | None:
        """Run recognition for one path."""
        result = self.worker.process_path(path, checkpoint=checkpoint)
        self.statistics = self.worker.statistics
        self.last_aggregation = aggregate_recognition_results([result] if result is not None else [])
        return result

    def _emit_completion(self) -> None:
        self._handle_event(
            RecognitionCompleted(
                total=self.statistics.processed,
                recognized=self.statistics.recognized,
                skipped=self.statistics.skipped,
                failed=self.statistics.failed,
            )
        )

    def _handle_event(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
