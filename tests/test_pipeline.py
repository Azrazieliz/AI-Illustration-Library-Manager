from __future__ import annotations

from engine.pipeline import PipelineJob, PipelineJobStatus, QueueManager, QueueType


def test_enqueue_and_dequeue() -> None:
    manager = QueueManager()
    job = PipelineJob(source_path="/tmp/image.jpg", queue_type=QueueType.DISCOVERY)

    manager.enqueue(QueueType.DISCOVERY, job)
    dequeued = manager.dequeue(QueueType.DISCOVERY)

    assert dequeued is not None
    assert dequeued.source_path == "/tmp/image.jpg"


def test_priority_and_pause_resume() -> None:
    manager = QueueManager()
    low = PipelineJob(source_path="low.jpg", queue_type=QueueType.DISCOVERY, priority=0)
    high = PipelineJob(source_path="high.jpg", queue_type=QueueType.DISCOVERY, priority=10)

    manager.enqueue(QueueType.DISCOVERY, low)
    manager.enqueue(QueueType.DISCOVERY, high)
    manager.pause_queue(QueueType.DISCOVERY)
    assert manager.dequeue(QueueType.DISCOVERY) is None
    manager.resume_queue(QueueType.DISCOVERY)
    dequeued = manager.dequeue(QueueType.DISCOVERY)

    assert dequeued is not None
    assert dequeued.source_path == "high.jpg"


def test_cancel_and_retry() -> None:
    manager = QueueManager()
    job = PipelineJob(source_path="retry.jpg", queue_type=QueueType.DISCOVERY)

    manager.enqueue(QueueType.DISCOVERY, job)
    manager.cancel(QueueType.DISCOVERY, job)
    assert job.status == PipelineJobStatus.CANCELLED

    retried = manager.retry(QueueType.DISCOVERY, job)
    assert retried.retry_count == 1
    assert retried.status == PipelineJobStatus.PENDING


def test_scanner_service_enqueues_discovery_jobs(tmp_path) -> None:
    from pathlib import Path

    from engine.scanner.scanner_service import ScannerService

    service = ScannerService()
    queued = service.enqueue_discovery_job(str(tmp_path / "scan.jpg"))

    assert queued.queue_type == QueueType.DISCOVERY
    assert queued.source_path == str(tmp_path / "scan.jpg")


def test_scanner_scan_enqueues_discovery_jobs(tmp_path) -> None:
    from engine.scanner.scanner_service import ScannerService

    service = ScannerService()
    image_path = tmp_path / "nested" / "scan.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"data")

    list(service.scan(root=tmp_path))

    queued = service.queue_manager.dequeue(QueueType.DISCOVERY)
    assert queued is not None
    assert queued.source_path == str(image_path)
