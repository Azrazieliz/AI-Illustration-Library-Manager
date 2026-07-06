from __future__ import annotations

from pathlib import Path
from typing import Iterator

from engine.events.base_event import BaseEvent
from engine.scanner.scanner_events import FileDiscovered
from engine.scanner.scanner_worker import ScannerWorker


class DiscoveryCoordinator:
    """Coordinates scanner discovery output into an event stream without owning pipeline logic."""

    def __init__(self, scanner_worker: ScannerWorker) -> None:
        self.scanner_worker = scanner_worker

    def discover(self, root: Path | None = None) -> Iterator[BaseEvent]:
        for path in self.scanner_worker.scan(root=root):
            yield FileDiscovered(event_type="file_discovered", file_path=path)
