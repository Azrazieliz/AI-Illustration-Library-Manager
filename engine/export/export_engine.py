from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from engine.export.export_backend import ExportBackend, InMemoryExportBackend
from engine.export.export_builder import ExportBuilder
from engine.export.export_events import ExportCompleted, ExportFailed, ExportSkipped, ExportStarted, Exported
from engine.export.export_models import ExportCheckpoint, ExportFilter, ExportOptions, ExportResult
from engine.export.export_statistics import ExportStatistics
from engine.logging import get_logger
from engine.repositories.export_repository import ExportRepository


class ExportEngine:
    """Exports canonical dataset entries into training-ready dataset formats."""

    def __init__(
        self,
        *,
        repository: ExportRepository | None = None,
        backend: ExportBackend | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.repository = repository or ExportRepository()
        self.backend = backend or InMemoryExportBackend()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = ExportStatistics()

    def export_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: ExportCheckpoint | None = None,
        options: ExportOptions | None = None,
        export_filter: ExportFilter | None = None,
        semantic: dict | None = None,
    ) -> list[ExportResult]:
        active_options = options or ExportOptions()
        self.statistics = ExportStatistics()
        self.statistics.start()
        results: list[ExportResult] = []
        resolved_paths = [str(Path(path).resolve()) for path in paths]

        batch_size = max(1, active_options.batch_size)
        for index in range(0, len(resolved_paths), batch_size):
            batch = resolved_paths[index : index + batch_size]
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(
                        self._export_one,
                        path,
                        checkpoint,
                        active_options,
                        export_filter,
                        semantic,
                    ): path
                    for path in batch
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result is not None:
                        results.append(result)

        self.statistics.finish()
        self._emit(
            ExportCompleted(
                total=self.statistics.processed,
                exported=self.statistics.exported,
                skipped=self.statistics.skipped,
                failed=self.statistics.failed,
            )
        )
        return results

    def export_path(
        self,
        path: Path | str,
        *,
        checkpoint: ExportCheckpoint | None = None,
        options: ExportOptions | None = None,
        export_filter: ExportFilter | None = None,
        semantic: dict | None = None,
    ) -> ExportResult | None:
        active_options = options or ExportOptions()
        return self._export_one(
            str(Path(path).resolve()),
            checkpoint,
            active_options,
            export_filter,
            semantic,
        )

    def _export_one(
        self,
        path: str,
        checkpoint: ExportCheckpoint | None,
        options: ExportOptions,
        export_filter: ExportFilter | None,
        semantic: dict | None,
    ) -> ExportResult | None:
        resolved = Path(path)

        if checkpoint is not None and checkpoint.is_processed(path, format_type=options.format_type):
            self.statistics.increment_processed()
            self.statistics.increment_skipped()
            self._emit(
                ExportSkipped(
                    path=resolved,
                    format_type=options.format_type,
                    reason="Already processed",
                )
            )
            return None

        self.statistics.increment_processed()
        self._emit(ExportStarted(path=resolved, format_type=options.format_type))

        try:
            repository = ExportRepository()
            builder = ExportBuilder(repository=repository)

            image = repository.get_image_by_path(path)
            if image is None:
                self.statistics.increment_skipped()
                self._emit(
                    ExportSkipped(
                        path=resolved,
                        format_type=options.format_type,
                        reason="Image not found",
                    )
                )
                return None

            existing = self.backend.get(options.format_type, image.id)
            if existing is not None and not options.overwrite and not options.rebuild:
                self.statistics.increment_skipped()
                self._emit(
                    ExportSkipped(
                        path=resolved,
                        format_type=options.format_type,
                        reason="Export already exists",
                    )
                )
                return None

            entry = repository.build_dataset_entry(path, semantic=semantic)
            if entry is None:
                self.statistics.increment_skipped()
                self._emit(
                    ExportSkipped(
                        path=resolved,
                        format_type=options.format_type,
                        reason="Dataset entry not available",
                    )
                )
                return None

            if not builder.matches_filter(entry, export_filter):
                self.statistics.increment_skipped()
                self._emit(
                    ExportSkipped(
                        path=resolved,
                        format_type=options.format_type,
                        reason="Filtered out",
                    )
                )
                return None

            record = builder.build_record(entry, format_type=options.format_type, semantic=semantic)
            rebuilt = existing is not None and (options.overwrite or options.rebuild)
            if rebuilt:
                record.exported_at = existing.exported_at
                record.updated_at = datetime.now(timezone.utc)

            if not options.dry_run:
                _ = self.backend.upsert(record)
                repository.save_export_manifest(
                    format_type=options.format_type,
                    image_id=record.image_id,
                    manifest=record.payload,
                )
                repository.save_export_provenance(
                    format_type=options.format_type,
                    image_id=record.image_id,
                    provenance=record.provenance,
                )

            if checkpoint is not None:
                checkpoint.add_processed(path, format_type=options.format_type)

            self.statistics.increment_exported()
            self._emit(
                Exported(
                    path=resolved,
                    image_id=record.image_id,
                    format_type=options.format_type,
                    dry_run=options.dry_run,
                    rebuilt=rebuilt,
                )
            )
            return ExportResult(
                image_id=record.image_id,
                path=resolved,
                format_type=options.format_type,
                record=record,
                dry_run=options.dry_run,
                rebuilt=rebuilt,
            )

        except Exception as e:
            self.statistics.increment_failed()
            self._emit(ExportFailed(path=resolved, format_type=options.format_type, error=str(e)))
            return None

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
