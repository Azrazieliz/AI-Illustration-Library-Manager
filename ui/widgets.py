from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class NavigationSidebar:
    items: list[str]
    active: str

    def select(self, panel_id: str) -> None:
        if panel_id in self.items:
            self.active = panel_id


@dataclass(slots=True)
class Toolbar:
    actions: dict[str, str]


@dataclass(slots=True)
class StatusBar:
    message: str = "Ready"
    progress: int = 0

    def set_status(self, message: str, *, progress: int | None = None) -> None:
        self.message = message
        if progress is not None:
            self.progress = max(0, min(100, int(progress)))


@dataclass(slots=True)
class ProgressDialog:
    title: str
    current: int = 0
    total: int = 100
    cancelled: bool = False

    def update(self, current: int, total: int | None = None) -> None:
        self.current = max(0, int(current))
        if total is not None:
            self.total = max(1, int(total))

    @property
    def percent(self) -> int:
        return int((self.current / max(1, self.total)) * 100)

    def cancel(self) -> None:
        self.cancelled = True


@dataclass(slots=True)
class ThumbnailGrid:
    thumbnails: list[Path] = field(default_factory=list)

    def set_items(self, items: list[Path]) -> None:
        self.thumbnails = list(items)


@dataclass(slots=True)
class ImagePreview:
    current_path: Path | None = None

    def show(self, image_path: Path | str) -> None:
        self.current_path = Path(image_path)


@dataclass(slots=True)
class MetadataInspector:
    metadata: dict[str, Any] = field(default_factory=dict)

    def inspect(self, metadata: dict[str, Any]) -> None:
        self.metadata = dict(metadata)


@dataclass(slots=True)
class LoggingConsole:
    lines: list[str] = field(default_factory=list)

    def append(self, message: str) -> None:
        self.lines.append(message)


@dataclass(slots=True)
class JobMonitor:
    queue_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    running_jobs: list[Any] = field(default_factory=list)

    def update(self, *, queue_stats: dict[str, dict[str, int]], running_jobs: list[Any]) -> None:
        self.queue_stats = dict(queue_stats)
        self.running_jobs = list(running_jobs)
