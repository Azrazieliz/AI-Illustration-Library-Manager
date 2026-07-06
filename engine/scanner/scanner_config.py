from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ScannerConfiguration:
    """Configuration for scanner behavior."""

    recursive_scan: bool = True
    follow_symlinks: bool = False
    ignored_directories: tuple[str, ...] = (".git", "__pycache__", ".venv", "node_modules")
    supported_extensions: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    batch_size: int = 100
    worker_count: int = 1
    scan_hidden_files: bool = False
    root_directory: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
