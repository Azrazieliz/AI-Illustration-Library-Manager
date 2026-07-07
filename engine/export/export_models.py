from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ExportFormatType(str, Enum):
    GENERIC = "generic"
    FLUX = "flux"
    SDXL = "sdxl"
    STABLE_DIFFUSION = "stable_diffusion"
    COMFYUI = "comfyui"


@dataclass(slots=True)
class ExportFilter:
    include_tags: set[str] = field(default_factory=set)
    exclude_tags: set[str] = field(default_factory=set)
    min_confidence: float = 0.0
    min_quality: float = 0.0
    min_completeness: float = 0.0
    image_ids: set[int] = field(default_factory=set)

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> ExportFilter:
        payload = metadata or {}
        include_tags = {
            str(item).strip().lower()
            for item in payload.get("include_tags", [])
            if str(item).strip()
        }
        exclude_tags = {
            str(item).strip().lower()
            for item in payload.get("exclude_tags", [])
            if str(item).strip()
        }
        image_ids = {
            int(item)
            for item in payload.get("image_ids", [])
            if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
        }
        return cls(
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            min_confidence=float(payload.get("min_confidence", 0.0)),
            min_quality=float(payload.get("min_quality", 0.0)),
            min_completeness=float(payload.get("min_completeness", 0.0)),
            image_ids=image_ids,
        )


@dataclass(slots=True)
class ExportOptions:
    format_type: ExportFormatType = ExportFormatType.GENERIC
    batch_size: int = 32
    dry_run: bool = False
    overwrite: bool = False
    incremental: bool = True
    rebuild: bool = False

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> ExportOptions:
        payload = metadata or {}
        raw_format = str(payload.get("export_format", ExportFormatType.GENERIC.value)).strip().lower()
        try:
            format_type = ExportFormatType(raw_format)
        except ValueError:
            format_type = ExportFormatType.GENERIC

        batch_size_raw = payload.get("batch_size", 32)
        try:
            batch_size = max(1, int(batch_size_raw))
        except (TypeError, ValueError):
            batch_size = 32

        return cls(
            format_type=format_type,
            batch_size=batch_size,
            dry_run=bool(payload.get("dry_run", False)),
            overwrite=bool(payload.get("overwrite", False)),
            incremental=bool(payload.get("incremental", True)),
            rebuild=bool(payload.get("rebuild", False)),
        )


@dataclass(slots=True)
class ExportRecord:
    image_id: int
    path: Path
    format_type: ExportFormatType
    payload: dict[str, Any]
    caption: str
    tags: list[str] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)
    exported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class ExportResult:
    image_id: int
    path: Path
    format_type: ExportFormatType
    record: ExportRecord
    dry_run: bool = False
    rebuilt: bool = False


@dataclass(slots=True)
class ExportCheckpoint:
    processed_keys: set[str] = field(default_factory=set)

    def _key(self, path: str | Path, format_type: ExportFormatType) -> str:
        return f"{format_type.value}:{path}"

    def add_processed(self, path: str | Path, *, format_type: ExportFormatType) -> None:
        self.processed_keys.add(self._key(path, format_type))

    def is_processed(self, path: str | Path, *, format_type: ExportFormatType) -> bool:
        return self._key(path, format_type) in self.processed_keys
