from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from engine.library_maintenance.maintenance_models import MaintenanceReport, MaintenanceTaskType
from engine.library_maintenance.maintenance_service import LibraryMaintenanceService


class LibraryMaintenanceWorker:
    """Background worker for maintenance jobs with pause/resume/cancellation."""

    _POLL_INTERVAL: float = 0.05

    def __init__(self, *, service: LibraryMaintenanceService | None = None) -> None:
        self.service = service or LibraryMaintenanceService()
        self._queue: Queue[tuple[str, list[MaintenanceTaskType] | None, dict[str, Any]]] = Queue()
        self._results: dict[str, MaintenanceReport] = {}
        self._stop_event = Event()
        self._pause_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="maintenance-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def submit_full(self, *, preview: bool = False, dry_run: bool = False) -> str:
        job_id = str(uuid4())
        self._queue.put((job_id, None, {"preview": preview, "dry_run": dry_run}))
        return job_id

    def submit_selected(self, tasks: list[MaintenanceTaskType], *, preview: bool = False, dry_run: bool = False) -> str:
        job_id = str(uuid4())
        self._queue.put((job_id, list(tasks), {"preview": preview, "dry_run": dry_run}))
        return job_id

    def cancel_job(self, job_id: str) -> None:
        self.service.cancel_job(job_id)

    def resume_job(self, job_id: str) -> MaintenanceReport:
        return self.service.resume_job(job_id)

    def rollback_job(self, job_id: str) -> int:
        return self.service.rollback_job(job_id)

    def result_for(self, job_id: str) -> MaintenanceReport | None:
        return self._results.get(job_id)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                continue
            try:
                job_id, tasks, kwargs = self._queue.get(timeout=self._POLL_INTERVAL)
            except Empty:
                continue
            try:
                if tasks is None:
                    report = self.service.run_full_maintenance(job_id=job_id, **kwargs)
                else:
                    report = self.service.run_selected_tasks(tasks, job_id=job_id, **kwargs)
                self._results[job_id] = report
            finally:
                self._queue.task_done()
