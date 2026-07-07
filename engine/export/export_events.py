from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.export.export_models import ExportFormatType


@dataclass(slots=True)
class ExportStarted:
    path: Path
    format_type: ExportFormatType


@dataclass(slots=True)
class Exported:
    path: Path
    image_id: int
    format_type: ExportFormatType
    dry_run: bool
    rebuilt: bool


@dataclass(slots=True)
class ExportSkipped:
    path: Path
    format_type: ExportFormatType
    reason: str


@dataclass(slots=True)
class ExportFailed:
    path: Path
    format_type: ExportFormatType
    error: str


@dataclass(slots=True)
class ExportCompleted:
    total: int
    exported: int
    skipped: int
    failed: int
