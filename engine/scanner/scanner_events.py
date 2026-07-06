from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.scanner.scanner_models import ScanEvent


@dataclass(slots=True, kw_only=True)
class ScanStarted(ScanEvent):
    """Raised when a scan begins."""

    root: Path | None = None


@dataclass(slots=True, kw_only=True)
class FolderScanned(ScanEvent):
    """Raised after a folder is processed."""

    folder: Path | None = None


@dataclass(slots=True, kw_only=True)
class FileDiscovered(ScanEvent):
    """Raised when a file is discovered during the scan."""

    file_path: Path | None = None


@dataclass(slots=True, kw_only=True)
class FileIgnored(ScanEvent):
    """Raised when a file is intentionally skipped."""

    file_path: Path | None = None
    reason: str | None = None


@dataclass(slots=True, kw_only=True)
class FileChanged(ScanEvent):
    """Raised when a file changes between scans."""

    file_path: Path


@dataclass(slots=True, kw_only=True)
class ScanPaused(ScanEvent):
    """Raised when the scan pauses."""


@dataclass(slots=True, kw_only=True)
class ScanResumed(ScanEvent):
    """Raised when the scan resumes."""


@dataclass(slots=True, kw_only=True)
class ScanCancelled(ScanEvent):
    """Raised when the scan is cancelled."""

    root: Path | None = None
    reason: str | None = None


@dataclass(slots=True, kw_only=True)
class ScanCompleted(ScanEvent):
    """Raised when a scan completes."""

    root: Path | None = None
