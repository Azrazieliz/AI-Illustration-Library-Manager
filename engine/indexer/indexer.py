from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from engine.indexer.indexer_events import FileDeleted, FileIndexed, FileModified, IndexCompleted, IndexStarted
from engine.indexer.indexer_exceptions import IndexerError
from engine.indexer.indexer_models import IndexDecision, IndexRecord, IndexState, IndexerCheckpoint
from engine.indexer.indexer_statistics import IndexerStatistics
from engine.repositories.image_repository import ImageRepository


class IncrementalIndexer:
    """Incremental filesystem indexer that consumes discovery data and synchronizes image records."""

    def __init__(self, repository: ImageRepository | None = None, callback: Callable[[object], None] | None = None) -> None:
        self.repository = repository or ImageRepository()
        self.callback = callback
        self.statistics = IndexerStatistics()
        self._checkpoint: IndexerCheckpoint | None = None
        self._states: dict[str, IndexState] = {}

    def index_paths(self, paths: Iterable[Path | str], *, checkpoint: IndexerCheckpoint | None = None) -> list[IndexRecord]:
        self.statistics.start()
        self._checkpoint = checkpoint
        self._states = self._load_existing_states()
        roots = [Path(path).expanduser().resolve() for path in paths]
        results: list[IndexRecord] = []
        seen_paths: set[str] = set()

        for root in roots:
            if root.is_file():
                self._index_path(root, results, seen_paths)
            else:
                self._emit(IndexStarted(root=root))
                self._index_directory(root, results, seen_paths)

        self._prune_deleted(seen_paths)
        self.statistics.complete()
        if roots:
            self._emit(IndexCompleted(root=roots[0]))
        return results

    def index(self, roots: Iterable[Path | str], *, checkpoint: IndexerCheckpoint | None = None) -> list[IndexRecord]:
        return self.index_paths(roots, checkpoint=checkpoint)

    def _index_directory(self, root: Path, results: list[IndexRecord], seen_paths: set[str]) -> None:
        if not root.exists():
            return
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            self._index_path(path, results, seen_paths)

    def _index_path(self, path: Path, results: list[IndexRecord], seen_paths: set[str]) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        seen_paths.add(str(resolved))
        if self._checkpoint is not None and str(resolved) in self._checkpoint.processed_paths:
            return
        record = self._build_record(resolved)
        decision = self._classify_record(record)
        if decision is IndexDecision.NEW:
            self._synchronize_record(record)
            self.statistics.new += 1
            self.statistics.processed += 1
            self._emit(FileIndexed(path=resolved, decision=decision.value))
            results.append(record)
        elif decision is IndexDecision.MODIFIED:
            self._synchronize_record(record)
            self.statistics.modified += 1
            self.statistics.processed += 1
            self._emit(FileIndexed(path=resolved, decision=decision.value))
            self._emit(FileModified(path=resolved))
            results.append(record)
        elif decision is IndexDecision.UNCHANGED:
            self.statistics.unchanged += 1
            self.statistics.processed += 1
        else:
            self.statistics.failed += 1
            raise IndexerError(f"Unsupported decision {decision}")
        self._states[str(resolved)] = IndexState(
            path=str(resolved),
            size=record.size,
            mtime=record.mtime,
            filename=record.filename,
            extension=record.extension,
            created_at=record.created_at,
            last_seen=record.mtime,
        )

    def _build_record(self, path: Path) -> IndexRecord:
        stat_result = path.stat()
        try:
            created_at = datetime.fromtimestamp(stat_result.st_ctime, tz=timezone.utc)
        except OSError:
            created_at = None
        return IndexRecord(
            source_path=str(path),
            filename=path.name,
            extension=path.suffix.lower() or None,
            size=stat_result.st_size,
            mtime=datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
            created_at=created_at,
            metadata={"exists": True},
        )

    def _classify_record(self, record: IndexRecord) -> IndexDecision:
        current = self._states.get(record.source_path)
        if current is None:
            existing = self.repository.get_by_path(record.source_path)
            if existing is None:
                return IndexDecision.NEW
            current = IndexState(
                path=record.source_path,
                size=existing.filesize,
                mtime=existing.modified_date,
                filename=existing.filename,
                extension=existing.extension,
                created_at=existing.scan_date,
                last_seen=existing.modified_date,
            )
            self._states[record.source_path] = current
        if current.size != record.size or not self._same_mtime(current.mtime, record.mtime):
            return IndexDecision.MODIFIED
        return IndexDecision.UNCHANGED

    def _load_existing_states(self) -> dict[str, IndexState]:
        states: dict[str, IndexState] = {}
        for image in self.repository.list_images():
            if not image.original_path:
                continue
            states[image.original_path] = IndexState(
                path=image.original_path,
                size=image.filesize,
                mtime=image.modified_date,
                filename=image.filename,
                extension=image.extension,
                created_at=image.scan_date,
                last_seen=image.modified_date,
            )
        return states

    def _same_mtime(self, left: datetime | None, right: datetime | None) -> bool:
        if left is None or right is None:
            return left is right
        return self._to_naive_utc(left) == self._to_naive_utc(right)

    @staticmethod
    def _to_naive_utc(dt: datetime) -> datetime:
        """Return *dt* as a naive UTC datetime truncated to whole seconds.

        SQLite stores datetimes as naive text without timezone information, so
        round-tripping a timezone-aware datetime through SQLite produces a naive
        value.  Normalising both sides to naive UTC before comparison ensures
        that a value read from the DB can be matched against a value produced
        from ``datetime.fromtimestamp(..., tz=timezone.utc)``.
        """
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.replace(microsecond=0)

    def _synchronize_record(self, record: IndexRecord) -> None:
        existing = self.repository.get_by_path(record.source_path)
        if existing is None:
            existing = self.repository.create_image(
                original_path=record.source_path,
                filename=record.filename,
                extension=record.extension,
            )
        existing.filename = record.filename
        existing.extension = record.extension
        existing.filesize = record.size
        existing.modified_date = record.mtime.replace(microsecond=0)
        existing.scan_date = record.mtime.replace(microsecond=0)
        existing.original_path = record.source_path
        self.repository.commit()

    def _prune_deleted(self, seen_paths: set[str]) -> None:
        existing_images = self.repository.list_images()
        for image in existing_images:
            if image.original_path not in seen_paths:
                self.repository.delete_image(image)
                self.statistics.deleted += 1
                self.statistics.processed += 1
                self._emit(FileDeleted(path=Path(image.original_path)))

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
