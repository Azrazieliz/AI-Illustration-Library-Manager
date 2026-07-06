from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import pytest

from engine.scanner import (
    ScanCompleted,
    ScanPaused,
    ScanResumed,
    ScanStarted,
    ScannerConfiguration,
    ScannerWorker,
)
from engine.scanner.scanner_exceptions import ScanCancelledError


def _write_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")


def test_recursive_traversal_yields_files_and_emits_events(tmp_path: Path) -> None:
    _write_file(tmp_path / "root.jpg")
    _write_file(tmp_path / "nested" / "child.png")
    _write_file(tmp_path / "nested" / "ignore.txt")

    events: list[object] = []
    worker = ScannerWorker(
        config=ScannerConfiguration(root_directory=tmp_path, supported_extensions=(".jpg", ".png")),
        callback=events.append,
    )

    discovered = list(worker.scan(root=tmp_path))

    assert [path.name for path in discovered] == ["child.png", "root.jpg"]
    assert any(isinstance(event, ScanStarted) for event in events)
    assert any(isinstance(event, ScanCompleted) for event in events)


def test_ignored_folders_and_extension_filtering(tmp_path: Path) -> None:
    _write_file(tmp_path / "keep.jpg")
    _write_file(tmp_path / ".hidden" / "hidden.png")
    _write_file(tmp_path / "ignored_dir" / "skip.jpg")
    _write_file(tmp_path / "nested" / "ignore.txt")

    worker = ScannerWorker(
        config=ScannerConfiguration(
            root_directory=tmp_path,
            supported_extensions=(".jpg",),
            ignored_directories=("ignored_dir",),
            scan_hidden_files=False,
        )
    )

    discovered = list(worker.scan(root=tmp_path))

    assert discovered == [tmp_path / "keep.jpg"]


def test_pause_resume_and_cancel(tmp_path: Path) -> None:
    for index in range(200):
        _write_file(tmp_path / f"folder{index}" / f"file{index}.jpg")

    worker = ScannerWorker(
        config=ScannerConfiguration(root_directory=tmp_path, supported_extensions=(".jpg",)),
    )

    scan_started = Event()
    paused = Event()
    resumed = Event()
    scan_cancelled = Event()
    results: list[Path] = []

    def handle_event(event: object) -> None:
        if isinstance(event, ScanStarted):
            scan_started.set()
        elif isinstance(event, ScanPaused):
            paused.set()
        elif isinstance(event, ScanResumed):
            resumed.set()

    worker.callback = handle_event

    def run_scan() -> None:
        try:
            for path in worker.scan(root=tmp_path):
                results.append(path)
        except ScanCancelledError:
            scan_cancelled.set()
            return

    thread = Thread(target=run_scan, daemon=True)
    thread.start()

    assert scan_started.wait(timeout=2)
    worker.pause()
    assert paused.wait(timeout=2)
    worker.resume()
    assert resumed.wait(timeout=2)
    worker.cancel()
    assert scan_cancelled.wait(timeout=2)

    assert worker.is_cancelled()


def test_statistics_are_updated(tmp_path: Path) -> None:
    _write_file(tmp_path / "one.jpg")
    _write_file(tmp_path / "two.txt")
    _write_file(tmp_path / "nested" / "three.png")

    worker = ScannerWorker(
        config=ScannerConfiguration(root_directory=tmp_path, supported_extensions=(".jpg", ".png"))
    )

    list(worker.scan(root=tmp_path))

    assert worker.statistics.files_scanned == 3
    assert worker.statistics.images_detected == 2
    assert worker.statistics.ignored_files == 1


def test_scan_can_be_cancelled_before_completion(tmp_path: Path) -> None:
    for index in range(200):
        _write_file(tmp_path / f"folder{index}" / f"file{index}.jpg")

    worker = ScannerWorker(config=ScannerConfiguration(root_directory=tmp_path, supported_extensions=(".jpg",)))

    worker.cancel()
    with pytest.raises(ScanCancelledError):
        next(worker.scan(root=tmp_path))
