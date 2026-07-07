from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from engine.database.models.image import Image
from engine.dataset.dataset_builder import DatasetBuilder
from engine.dataset.dataset_models import DatasetEntry
from engine.repositories.base_repository import BaseRepository
from engine.repositories.dataset_repository import DatasetRepository
from engine.export.export_models import ExportFormatType


class ExportRepository(BaseRepository[Image]):
    """Repository supplying dataset data and export persistence metadata."""

    _manifest_store: dict[tuple[str, int], dict[str, Any]] = {}
    _provenance_store: dict[tuple[str, int], list[str]] = {}
    _lock = Lock()

    def __init__(self) -> None:
        super().__init__(Image)

    def get_image_by_path(self, path: str | Path) -> Image | None:
        return self.session.query(Image).filter(Image.original_path == str(path)).first()

    def build_dataset_entry(self, path: str | Path, *, semantic: dict | None = None) -> DatasetEntry | None:
        dataset_repository = DatasetRepository()
        builder = DatasetBuilder(dataset_repository)
        return builder.build(path, semantic=semantic)

    def save_export_manifest(
        self,
        *,
        format_type: ExportFormatType,
        image_id: int,
        manifest: dict[str, Any],
    ) -> None:
        key = (format_type.value, image_id)
        with self._lock:
            self._manifest_store[key] = dict(manifest)

    def get_export_manifest(self, *, format_type: ExportFormatType, image_id: int) -> dict[str, Any]:
        key = (format_type.value, image_id)
        with self._lock:
            return dict(self._manifest_store.get(key, {}))

    def save_export_provenance(
        self,
        *,
        format_type: ExportFormatType,
        image_id: int,
        provenance: list[str],
    ) -> None:
        key = (format_type.value, image_id)
        with self._lock:
            self._provenance_store[key] = list(provenance)

    def get_export_provenance(self, *, format_type: ExportFormatType, image_id: int) -> list[str]:
        key = (format_type.value, image_id)
        with self._lock:
            return list(self._provenance_store.get(key, []))

    def list_exported_image_ids(self, *, format_type: ExportFormatType) -> list[int]:
        with self._lock:
            return [image_id for (fmt, image_id) in self._manifest_store if fmt == format_type.value]

    def count_exports(self, *, format_type: ExportFormatType) -> int:
        return len(self.list_exported_image_ids(format_type=format_type))
