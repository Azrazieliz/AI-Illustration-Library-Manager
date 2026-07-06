from __future__ import annotations

from threading import Event, Lock, Thread
from time import sleep
from typing import Callable

from engine.logging import get_logger
from engine.scanner.scanner_config import ScannerConfiguration
from engine.scanner.scanner_exceptions import ScanCancelledError, ScannerError
from engine.scanner.scanner_models import ScanStatus
from engine.scanner.scanner_statistics import ScannerStatistics


class ScannerWorker:
    """Asynchronous-ready worker that owns scanner lifecycle state."""

    def __init__(
        self,
        config: ScannerConfiguration | None = None,
        statistics: ScannerStatistics | None = None,
        callback: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config or ScannerConfiguration()
        self.statistics = statistics or ScannerStatistics()
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._pause_event = Event()
        self._lock = Lock()
        self._status = ScanStatus.IDLE

    def start(self) -> None:
        """Start the worker."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._pause_event.clear()
            self._status = ScanStatus.RUNNING
            self.statistics.start()
            self._thread = Thread(target=self._run, daemon=True)
            self._thread.start()

    def pause(self) -> None:
        """Pause the worker."""
        with self._lock:
            if self._status == ScanStatus.RUNNING:
                self._pause_event.set()
                self._status = ScanStatus.PAUSED

    def resume(self) -> None:
        """Resume the worker."""
        with self._lock:
            if self._status == ScanStatus.PAUSED:
                self._pause_event.clear()
                self._status = ScanStatus.RUNNING

    def cancel(self) -> None:
        """Cancel the worker."""
        with self._lock:
            self._stop_event.set()
            self._status = ScanStatus.CANCELLED

    def is_running(self) -> bool:
        """Return True when the worker is running."""
        return self._status == ScanStatus.RUNNING

    def is_paused(self) -> bool:
        """Return True when the worker is paused."""
        return self._status == ScanStatus.PAUSED

    def progress(self) -> float:
        """Return the worker's progress proxy."""
        return 0.0

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                if self._pause_event.is_set():
                    sleep(0.1)
                    continue
                self._emit("working")
                sleep(0.01)
                if self._stop_event.is_set():
                    raise ScanCancelledError("Scan cancelled")
        except ScanCancelledError as exc:
            self.logger.warning("Scanner cancelled: %s", exc)
            self._status = ScanStatus.CANCELLED
        except ScannerError as exc:
            self.logger.exception("Scanner error: %s", exc)
            self._status = ScanStatus.CANCELLED
        else:
            self._status = ScanStatus.COMPLETED
            self.statistics.complete()
            self._emit("completed")

    def _emit(self, message: str) -> None:
        if self.callback is not None:
            self.callback(message)
