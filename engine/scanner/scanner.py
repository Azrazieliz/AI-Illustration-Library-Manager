from __future__ import annotations

from pathlib import Path
from typing import Iterator

from engine.logging import get_logger
from engine.pipeline import QueueManager
from engine.scanner.scanner_config import ScannerConfiguration
from engine.scanner.scanner_service import ScannerService
from engine.scanner.scanner_statistics import ScannerStatistics


class ScannerManager:
    """Top-level manager that owns the scanner subsystem."""

    def __init__(
        self,
        config: ScannerConfiguration | None = None,
        statistics: ScannerStatistics | None = None,
        queue_manager: QueueManager | None = None,
    ) -> None:
        self.config = config or ScannerConfiguration()
        self.statistics = statistics or ScannerStatistics()
        self.logger = get_logger(self.__class__.__name__)
        self.service = ScannerService(
            config=self.config,
            statistics=self.statistics,
            queue_manager=queue_manager,
        )

    def initialize(self) -> ScannerService:
        """Initialize the scanner subsystem and return the service."""
        self.logger.info("Scanner subsystem initialized")
        return self.service

    def scan(self, root: Path | None = None) -> Iterator[Path]:
        """Run a recursive scan through the service layer."""
        return self.service.scan(root=root)
