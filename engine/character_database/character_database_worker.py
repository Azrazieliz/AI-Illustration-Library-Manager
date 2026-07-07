from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from engine.character_database.character_database_models import WorkerCheckpoint, WorkerJob, WorkerJobStatus, WorkerTaskType
from engine.character_database.character_database_service import CharacterDatabaseService


class CharacterDatabaseWorker:
    """Background worker for validation and import tasks with resume/cancel support."""

    _POLL_INTERVAL: float = 0.05

    def __init__(self, *, service: CharacterDatabaseService | None = None) -> None:
        self.service = service or CharacterDatabaseService()
        self._queue: Queue[tuple[str, WorkerTaskType, dict[str, Any], bool]] = Queue()
        self._results: dict[str, Any] = {}
        self._jobs: dict[str, WorkerJob] = {}
        self._checkpoints: dict[str, WorkerCheckpoint] = {}
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="character-database-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def submit_validation(self) -> str:
        job_id = str(uuid4())
        self._enqueue(job_id, WorkerTaskType.VALIDATE, payload={}, resumed=False)
        return job_id

    def submit_import_characters(self, payloads: list[dict]) -> str:
        job_id = str(uuid4())
        self._enqueue(job_id, WorkerTaskType.IMPORT_CHARACTERS, payload={"payloads": list(payloads)}, resumed=False)
        return job_id

    def submit_import_series(self, payloads: list[dict]) -> str:
        job_id = str(uuid4())
        self._enqueue(job_id, WorkerTaskType.IMPORT_SERIES, payload={"payloads": list(payloads)}, resumed=False)
        return job_id

    def submit_merge_database(self, payload: dict) -> str:
        job_id = str(uuid4())
        self._enqueue(job_id, WorkerTaskType.MERGE_DATABASE, payload={"payload": dict(payload)}, resumed=False)
        return job_id

    def cancel(self, job_id: str) -> None:
        self.service.request_cancel(job_id)
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = WorkerJobStatus.CANCELLED

    def resume(self, job_id: str) -> str:
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job id: {job_id}")
        payload = {"payloads": []}
        if job.task_type in {WorkerTaskType.IMPORT_CHARACTERS, WorkerTaskType.IMPORT_SERIES}:
            previous = self._results.get(f"{job_id}-payload")
            payload = {"payloads": list(previous or [])}
        if job.task_type is WorkerTaskType.MERGE_DATABASE:
            previous_merge = self._results.get(f"{job_id}-payload")
            payload = {"payload": dict(previous_merge or {})}
        self._enqueue(job_id, job.task_type, payload=payload, resumed=True)
        return job_id

    def result_for(self, job_id: str):
        return self._results.get(job_id)

    def job_for(self, job_id: str) -> WorkerJob | None:
        return self._jobs.get(job_id)

    def _enqueue(self, job_id: str, task_type: WorkerTaskType, payload: dict[str, Any], resumed: bool) -> None:
        self._jobs[job_id] = WorkerJob(job_id=job_id, task_type=task_type, status=WorkerJobStatus.PENDING)
        self._queue.put((job_id, task_type, payload, resumed))

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id, task_type, payload, resumed = self._queue.get(timeout=self._POLL_INTERVAL)
            except Empty:
                continue
            try:
                job = self._jobs[job_id]
                job.status = WorkerJobStatus.RUNNING
                result = self._dispatch(job_id=job_id, task_type=task_type, payload=payload, resumed=resumed)
                checkpoint = self.service.engine.checkpoint_for(job_id)
                self._checkpoints[job_id] = checkpoint
                self._results[job_id] = result
                if checkpoint.processed < checkpoint.total:
                    job.status = WorkerJobStatus.CANCELLED
                else:
                    job.status = WorkerJobStatus.COMPLETED
            except Exception as exc:  # pragma: no cover - defensive fallback
                job = self._jobs[job_id]
                job.status = WorkerJobStatus.FAILED
                job.error_message = str(exc)
                self._results[job_id] = None
            finally:
                self._queue.task_done()

    def _dispatch(self, *, job_id: str, task_type: WorkerTaskType, payload: dict[str, Any], resumed: bool):
        if task_type is WorkerTaskType.VALIDATE:
            return self.service.validate_database()

        if task_type is WorkerTaskType.IMPORT_CHARACTERS:
            items = list(payload.get("payloads", []))
            self._results[f"{job_id}-payload"] = list(items)
            return self.service.import_characters(items, job_id=job_id, resumed=resumed)

        if task_type is WorkerTaskType.IMPORT_SERIES:
            items = list(payload.get("payloads", []))
            self._results[f"{job_id}-payload"] = list(items)
            return self.service.import_series(items, job_id=job_id, resumed=resumed)

        merge_payload = dict(payload.get("payload", {}))
        self._results[f"{job_id}-payload"] = dict(merge_payload)
        return self.service.merge_database(merge_payload, job_id=job_id, resumed=resumed)
