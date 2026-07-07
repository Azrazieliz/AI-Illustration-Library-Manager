from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from engine.bulk.bulk_engine import BulkEngine
from engine.bulk.bulk_models import BulkRequest, BulkResult
from engine.bulk.bulk_service import BulkService


class BulkWorker:
    """Background worker for queued bulk requests."""

    _POLL_INTERVAL: float = 0.05

    def __init__(self, *, engine: BulkEngine | None = None, service: BulkService | None = None) -> None:
        self.engine = engine or BulkEngine(callback=self._handle_event)
        self.service = service or BulkService(engine=self.engine)
        self._queue: Queue[tuple[str, BulkRequest, dict[str, Any]]] = Queue()
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="bulk-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def submit(self, request: BulkRequest, **kwargs: Any) -> str:
        batch_id = kwargs.pop("batch_id", str(uuid4()))
        self._queue.put((batch_id, request, kwargs))
        return batch_id

    def process_requests(self, requests: list[BulkRequest], **kwargs: Any) -> list[BulkResult]:
        results: list[BulkResult] = []
        for request in requests:
            results.append(self.service.engine.execute(request, **kwargs))
        return results

    def process_request(self, request: BulkRequest, **kwargs: Any) -> BulkResult:
        return self.service.engine.execute(request, **kwargs)

    def cancel_batch(self, batch_id: str) -> None:
        self.service.cancel_batch(batch_id)

    def resume_batch(self, batch_id: str) -> BulkResult:
        return self.service.resume_batch(batch_id)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                batch_id, request, kwargs = self._queue.get(timeout=self._POLL_INTERVAL)
            except Empty:
                continue
            kwargs.setdefault("batch_id", batch_id)
            try:
                self.service.engine.execute(request, **kwargs)
            finally:
                self._queue.task_done()

    def _handle_event(self, event: object) -> None:
        return None
