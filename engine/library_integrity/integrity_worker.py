from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from typing import Literal
from uuid import uuid4

from engine.library_integrity.integrity_models import IntegrityCheckpoint, IntegrityReport
from engine.library_integrity.integrity_service import LibraryIntegrityService

ScanMode = Literal["full", "quick", "database", "filesystem"]


class LibraryIntegrityWorker:
    """Background worker for integrity scans with cancellation and resume."""

    _POLL_INTERVAL: float = 0.05

    def __init__(self, *, service: LibraryIntegrityService | None = None) -> None:
        self.service = service or LibraryIntegrityService()
        self._queue: Queue[tuple[str, ScanMode, bool]] = Queue()
        self._results: dict[str, IntegrityReport] = {}
        self._modes: dict[str, ScanMode] = {}
        self._checkpoints: dict[str, IntegrityCheckpoint] = {}
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="integrity-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def submit(self, *, mode: ScanMode = "full") -> str:
        scan_id = str(uuid4())
        self._modes[scan_id] = mode
        self._checkpoints.setdefault(scan_id, IntegrityCheckpoint())
        self._queue.put((scan_id, mode, False))
        return scan_id

    def run_now(self, *, mode: ScanMode = "full") -> IntegrityReport:
        return self._dispatch(mode=mode)

    def cancel(self, scan_id: str) -> None:
        self.service.cancel_scan(scan_id)

    def resume(self, scan_id: str) -> str:
        mode = self._modes.get(scan_id, "full")
        self._queue.put((scan_id, mode, True))
        return scan_id

    def result_for(self, scan_id: str) -> IntegrityReport | None:
        return self._results.get(scan_id)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                scan_id, mode, resumed = self._queue.get(timeout=self._POLL_INTERVAL)
            except Empty:
                continue
            try:
                checkpoint = self._checkpoints.get(scan_id)
                report = self._dispatch(scan_id=scan_id, mode=mode, checkpoint=checkpoint, resumed=resumed)
                self._results[scan_id] = report
                self._checkpoints[scan_id] = self.service.checkpoint_for(scan_id)
            finally:
                self._queue.task_done()

    def _dispatch(
        self,
        *,
        mode: ScanMode,
        scan_id: str | None = None,
        checkpoint: IntegrityCheckpoint | None = None,
        resumed: bool = False,
    ) -> IntegrityReport:
        if mode == "quick":
            return self.service.run_quick_scan(scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)
        if mode == "database":
            return self.service.run_database_scan(scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)
        if mode == "filesystem":
            return self.service.run_filesystem_scan(scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)
        return self.service.run_full_scan(scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)
