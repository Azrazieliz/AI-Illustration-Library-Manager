from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from engine.dataset.dataset_backend import DatasetBackend, InMemoryDatasetBackend
from engine.dataset.dataset_builder import DatasetBuilder
from engine.dataset.dataset_events import (
    DatasetBuilt,
    DatasetCompleted,
    DatasetFailed,
    DatasetSkipped,
    DatasetStarted,
)
from engine.dataset.dataset_models import DatasetBuildResult, DatasetCheckpoint, DatasetEntry
from engine.dataset.dataset_statistics import DatasetStatistics
from engine.logging import get_logger
from engine.repositories.dataset_repository import DatasetRepository


class DatasetEngine:
    """Builds canonical AI-training-ready dataset entries."""

    def __init__(
        self,
        *,
        repository: DatasetRepository | None = None,
        backend: DatasetBackend | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.repository = repository or DatasetRepository()
        self.backend = backend or InMemoryDatasetBackend()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = DatasetStatistics()

    def build_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: DatasetCheckpoint | None = None,
        rebuild: bool = False,
        semantic: dict | None = None,
    ) -> list[DatasetBuildResult]:
        """Build canonical dataset entries for many paths in parallel."""
        self.statistics = DatasetStatistics()
        self.statistics.start()
        results: list[DatasetBuildResult] = []
        resolved_paths = [str(Path(path).resolve()) for path in paths]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._build_one, path, checkpoint, rebuild, semantic): path
                for path in resolved_paths
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)

        self.statistics.finish()
        self._emit(
            DatasetCompleted(
                total=self.statistics.processed,
                built=self.statistics.built,
                skipped=self.statistics.skipped,
                failed=self.statistics.failed,
            )
        )
        return results

    def build_path(
        self,
        path: Path | str,
        *,
        checkpoint: DatasetCheckpoint | None = None,
        rebuild: bool = False,
        semantic: dict | None = None,
    ) -> DatasetBuildResult | None:
        """Build canonical dataset entry for one path."""
        return self._build_one(str(Path(path).resolve()), checkpoint, rebuild, semantic)

    def _build_one(
        self,
        path: str,
        checkpoint: DatasetCheckpoint | None,
        rebuild: bool,
        semantic: dict | None,
    ) -> DatasetBuildResult | None:
        resolved = Path(path)

        if checkpoint is not None and checkpoint.is_processed(path):
            self.statistics.increment_processed()
            self.statistics.increment_skipped()
            self._emit(DatasetSkipped(path=resolved, reason="Already processed"))
            return None

        self.statistics.increment_processed()
        self._emit(DatasetStarted(path=resolved))

        try:
            repository = DatasetRepository()
            builder = DatasetBuilder(repository)
            image = repository.get_image_by_path(path)
            if image is None:
                self.statistics.increment_skipped()
                self._emit(DatasetSkipped(path=resolved, reason="Image not found"))
                return None

            existing = self.backend.get(image.id)
            if existing is not None and not rebuild:
                self.statistics.increment_skipped()
                self._emit(DatasetSkipped(path=resolved, reason="Dataset entry already exists"))
                return None

            entry = builder.build(path, semantic=semantic)
            if entry is None:
                self.statistics.increment_skipped()
                self._emit(DatasetSkipped(path=resolved, reason="Build prerequisites missing"))
                return None

            if existing is not None and rebuild:
                entry.built_at = existing.built_at
                entry.updated_at = datetime.now(timezone.utc)
            else:
                entry.updated_at = entry.built_at

            _ = self.backend.upsert(entry)
            repository.save_dataset_provenance(entry.image_id, entry.provenance)

            if checkpoint is not None:
                checkpoint.add_processed(path)

            self.statistics.increment_built()
            rebuilt = existing is not None and rebuild
            self._emit(DatasetBuilt(path=resolved, image_id=entry.image_id, rebuilt=rebuilt))
            return DatasetBuildResult(
                image_id=entry.image_id,
                path=resolved,
                entry=entry,
                rebuilt=rebuilt,
            )

        except Exception as e:
            self.statistics.increment_failed()
            self._emit(DatasetFailed(path=resolved, error=str(e)))
            return None

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
