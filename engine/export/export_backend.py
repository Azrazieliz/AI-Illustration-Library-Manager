from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock

from engine.export.export_models import ExportFormatType, ExportRecord


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
