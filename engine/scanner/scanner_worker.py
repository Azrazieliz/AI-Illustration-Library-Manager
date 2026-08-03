from __future__ import annotations

import os
from pathlib import Path
from threading import Condition, Event, Lock, Thread
from typing import Callable, Iterator

from engine.logging import get_logger
from engine.scanner.scanner_config import ScannerConfiguration
from engine.scanner.scanner_events import (
    FileDiscovered,
    FileIgnored,
    FolderScanned,
    ScanCancelled,
    ScanCompleted,
    ScanPaused,
    ScanResumed,
    ScanStarted,
)
from engine.scanner.scanner_exceptions import ScanCancelledError, ScannerError
from engine.scanner.scanner_models import ScanStatus
from engine.scanner.scanner_statistics import ScannerStatistics


class ScannerWorker:
    """Asynchronous-ready worker that owns scanner lifecycle state."""

    def __init__(
        self,
        config: ScannerConfiguration | None = None,
        statistics: ScannerStatistics | None = None,
        callback: Callable[[object], None] | None = None,
    ) -> None:
        self.config = config or ScannerConfiguration()
        self.statistics = statistics or ScannerStatistics()
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._pause_event = Event()
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._status = ScanStatus.IDLE
        self._progress = 0.0
        self._root: Path | None = None

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
        with self._condition:
            if self._status in {ScanStatus.RUNNING, ScanStatus.IDLE}:
                self._pause_event.set()
                self._status = ScanStatus.PAUSED
                self._condition.notify_all()
                self._emit(ScanPaused(event_type="scan_paused"))

    def resume(self) -> None:
        """Resume the worker."""
        with self._condition:
            if self._status == ScanStatus.PAUSED:
                self._pause_event.clear()
                self._status = ScanStatus.RUNNING
                self._condition.notify_all()
                self._emit(ScanResumed(event_type="scan_resumed"))

    def cancel(self) -> None:
        """Cancel the worker."""
        with self._condition:
            self._stop_event.set()
            self._pause_event.clear()
            if self._status != ScanStatus.COMPLETED:
                self._status = ScanStatus.CANCELLED
            self._condition.notify_all()

    def is_running(self) -> bool:
        """Return True when the worker is running."""
        with self._lock:
            return self._status == ScanStatus.RUNNING

    def is_paused(self) -> bool:
        """Return True when the worker is paused."""
        with self._lock:
            return self._status == ScanStatus.PAUSED

    def is_cancelled(self) -> bool:
        """Return True when the worker is cancelled."""
        with self._lock:
            return self._status == ScanStatus.CANCELLED

    def progress(self) -> float:
        """Return the worker's progress proxy."""
        return self._progress

    def scan(self, root: Path | None = None) -> Iterator[Path]:
        """Recursively scan a directory and yield discovered image paths."""
        root_path = self._resolve_root(root)
        if self._stop_event.is_set():
            raise ScanCancelledError("Scan cancelled before start")

        self._root = root_path
        self._stop_event.clear()
        self._pause_event.clear()
        with self._lock:
            self._status = ScanStatus.RUNNING
        self._progress = 0.0
        self.statistics.start()
        self._emit(ScanStarted(event_type="scan_started", root=root_path))

        try:
            yield from self._scan_directory(root_path)
        except ScanCancelledError as exc:
            with self._lock:
                self._status = ScanStatus.CANCELLED
            self.statistics.complete()
            self._emit(ScanCancelled(event_type="scan_cancelled", root=root_path, reason=str(exc)))
            raise
        except ScannerError as exc:
            self._status = ScanStatus.CANCELLED
            self.statistics.errors += 1
            self.statistics.complete()
            self.logger.exception("Scanner error during scan", extra={"root": str(root_path)})
            self._emit(ScanCancelled(event_type="scan_cancelled", root=root_path, reason=str(exc)))
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            self._status = ScanStatus.CANCELLED
            self.statistics.errors += 1
            self.statistics.complete()
            self.logger.exception("Unexpected scanner failure", extra={"root": str(root_path)})
            self._emit(ScanCancelled(event_type="scan_cancelled", root=root_path, reason=str(exc)))
            raise
        else:
            with self._lock:
                self._status = ScanStatus.COMPLETED
            self.statistics.complete()
            self._emit(ScanCompleted(event_type="scan_completed", root=root_path))

    def _run(self) -> None:
        try:
            for _ in self.scan():
                continue
        except ScanCancelledError as exc:
            self.logger.warning("Scanner cancelled: %s", exc)
            self._status = ScanStatus.CANCELLED
        except ScannerError as exc:
            self.logger.exception("Scanner error: %s", exc)
            self._status = ScanStatus.CANCELLED
        else:
            self._status = ScanStatus.COMPLETED

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)

    def _resolve_root(self, root: Path | None = None) -> Path:
        if root is not None:
            return Path(root).expanduser().resolve()
        if self.config.root_directory is not None:
            return Path(self.config.root_directory).expanduser().resolve()
        return Path.cwd()
    def _scan_directory(self, root_path: Path) -> Iterator[Path]:
        if not root_path.exists():
            raise FileNotFoundError(f"Scan root does not exist: {root_path}")
        if not root_path.is_dir():
            raise NotADirectoryError(f"Scan root is not a directory: {root_path}")

        self.statistics.folders_scanned += 1
        self._emit(FolderScanned(event_type="folder_scanned", folder=root_path))
        self._progress = 0.0

        stack: list[tuple[Path, os.DirEntry[str]] | tuple[Path, object]] = []
        stack.append((root_path, os.scandir(root_path)))

        while stack:
            self._check_pause_and_cancel()
            current_path, entries = stack[-1]
            try:
                entry = next(entries)
            except StopIteration:
                if hasattr(entries, "close"):
                    entries.close()
                stack.pop()
                continue
            except FileNotFoundError as exc:
                self.statistics.errors += 1
                self._emit(FileIgnored(event_type="file_ignored", file_path=current_path, reason=str(exc)))
                continue

            entry_path = Path(entry.path)
            self._check_pause_and_cancel()

            if entry.is_symlink():
                if not self.config.follow_symlinks or not entry.exists():
                    self.statistics.ignored_files += 1
                    self._emit(FileIgnored(event_type="file_ignored", file_path=entry_path, reason="broken symlink"))
                    continue

            if entry.is_dir(follow_symlinks=self.config.follow_symlinks):
                if self._should_ignore_directory(entry.name):
                    self.statistics.ignored_files += 1
                    self._emit(FileIgnored(event_type="file_ignored", file_path=entry_path, reason="ignored directory"))
                    continue

                self.statistics.folders_scanned += 1
                self._emit(FolderScanned(event_type="folder_scanned", folder=entry_path))
                stack.append((entry_path, os.scandir(entry_path)))
                self._progress = min(1.0, self._progress + 0.01)
                continue

            if entry.is_file(follow_symlinks=self.config.follow_symlinks):
                self.statistics.files_scanned += 1
                self._progress = min(1.0, self._progress + 0.01)

                if self._should_ignore_file(entry_path):
                    self.statistics.ignored_files += 1
                    self._emit(FileIgnored(event_type="file_ignored", file_path=entry_path, reason=self._ignore_reason(entry_path)))
                    continue

                if self._is_supported_image(entry_path):
                    self.statistics.images_detected += 1
                    self._emit(FileDiscovered(event_type="file_discovered", file_path=entry_path))
                    yield entry_path
                    continue

                self.statistics.ignored_files += 1
                self._emit(FileIgnored(event_type="file_ignored", file_path=entry_path, reason="unsupported extension"))
                continue

            self.statistics.ignored_files += 1
            self._emit(FileIgnored(event_type="file_ignored", file_path=entry_path, reason="unsupported entry"))

    def _check_pause_and_cancel(self) -> None:
        while True:
            with self._lock:
                paused = self._pause_event.is_set()
                cancelled = self._stop_event.is_set()
            if cancelled:
                raise ScanCancelledError("Scan cancelled")
            if not paused:
                break
            self._wait_for_resume_or_cancel()

    def _wait_for_resume_or_cancel(self) -> None:
        with self._condition:
            while self._pause_event.is_set() and not self._stop_event.is_set():
                self._condition.wait()
            if self._stop_event.is_set():
                raise ScanCancelledError("Scan cancelled")

    def _should_ignore_directory(self, name: str) -> bool:
        if not self.config.scan_hidden_files and name.startswith("."):
            return True
        return name in self.config.ignored_directories

    def _should_ignore_file(self, path: Path) -> bool:
        if not self.config.scan_hidden_files and any(part.startswith(".") for part in path.parts):
            return True
        return not self._is_supported_image(path)

    def _ignore_reason(self, path: Path) -> str:
        if not self.config.scan_hidden_files and any(part.startswith(".") for part in path.parts):
            return "hidden file"
        return "unsupported extension"

    def _is_supported_image(self, path: Path) -> bool:
        return path.suffix.lower() in self.config.supported_extensions
