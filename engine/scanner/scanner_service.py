from __future__ import annotations

from pathlib import Path
from typing import Iterator

from engine.logging import get_logger
from engine.scanner.scanner_config import ScannerConfiguration
from engine.scanner.scanner_statistics import ScannerStatistics
from engine.scanner.scanner_worker import ScannerWorker
from engine.services import ImageService, JobService, TransactionService


class ScannerService:
    """Service façade that integrates the scanner foundation with existing services."""

    def __init__(
        self,
        config: ScannerConfiguration | None = None,
        statistics: ScannerStatistics | None = None,
    ) -> None:
        self.config = config or ScannerConfiguration()
        self.statistics = statistics or ScannerStatistics()
        self.logger = get_logger(self.__class__.__name__)
        self.job_service = JobService()
        self.image_service = ImageService()
        self.transaction_service = TransactionService()
        self.worker = ScannerWorker(config=self.config, statistics=self.statistics)

    def start_scan(self) -> ScannerWorker:
        """Start the scanner worker."""
        self.worker.start()
        return self.worker

    def scan(self, root: Path | None = None) -> Iterator[Path]:
        """Run a recursive scanner pass and yield discovered image paths."""
        return self.worker.scan(root=root)

    def pause_scan(self) -> None:
        """Pause the scanner worker."""
        self.worker.pause()

    def resume_scan(self) -> None:
        """Resume the scanner worker."""
        self.worker.resume()

    def cancel_scan(self) -> None:
        """Cancel the scanner worker."""
        self.worker.cancel()
