from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock
from typing import TYPE_CHECKING

from engine.export.export_models import ExportFormatType, ExportRecord

if TYPE_CHECKING:
    from engine.repositories.export_repository import ExportRepository


class ExportBackend(ABC):
    """Abstract backend for export artifacts."""

    @abstractmethod
    def get(self, format_type: ExportFormatType, image_id: int) -> ExportRecord | None:
        """Retrieve an existing export record by format and image id."""

    @abstractmethod
    def upsert(self, record: ExportRecord) -> bool:
        """Insert or update export record. Returns True when a new record is created."""

    @abstractmethod
    def list_for_format(self, format_type: ExportFormatType) -> list[ExportRecord]:
        """List all records for one export format."""


class InMemoryExportBackend(ExportBackend):
    """Default in-memory export backend for local runs and tests."""

    def __init__(self) -> None:
        self._records: dict[ExportFormatType, dict[int, ExportRecord]] = {}
        self._lock = Lock()

    def get(self, format_type: ExportFormatType, image_id: int) -> ExportRecord | None:
        with self._lock:
            return self._records.get(format_type, {}).get(image_id)

    def upsert(self, record: ExportRecord) -> bool:
        with self._lock:
            by_format = self._records.setdefault(record.format_type, {})
            created = record.image_id not in by_format
            by_format[record.image_id] = record
            return created

    def list_for_format(self, format_type: ExportFormatType) -> list[ExportRecord]:
        with self._lock:
            return list(self._records.get(format_type, {}).values())


class RepositoryExportBackend(ExportBackend):
    """SQLite-backed export backend used by the production composition root."""

    def __init__(self, repository: ExportRepository | None = None) -> None:
        if repository is None:
            from engine.repositories.export_repository import ExportRepository

            repository = ExportRepository()
        self.repository = repository

    def get(self, format_type: ExportFormatType, image_id: int) -> ExportRecord | None:
        return self.repository.get_export_record(format_type=format_type, image_id=image_id)

    def upsert(self, record: ExportRecord) -> bool:
        return self.repository.upsert_export_record(record)

    def list_for_format(self, format_type: ExportFormatType) -> list[ExportRecord]:
        return self.repository.list_export_records(format_type=format_type)
