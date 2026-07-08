from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from engine.adaptive_learning.adaptive_exceptions import AdaptiveCheckpointError
from engine.adaptive_learning.adaptive_models import (
    AdaptiveCheckpoint,
    AdaptiveEvidence,
    AdaptiveLearningResult,
    AdaptiveProgress,
    AdaptiveTaskStatus,
    AdaptiveTaskType,
)
from engine.adaptive_learning.adaptive_service import AdaptiveLearningService


class AdaptiveLearningWorker:
    """Background worker for incremental adaptive training and rollback tasks."""

    _POLL_INTERVAL: float = 0.05

    def __init__(self, *, service: AdaptiveLearningService | None = None) -> None:
        self.service = service or AdaptiveLearningService()
        self._queue: Queue[tuple[str, AdaptiveTaskType, dict[str, Any]]] = Queue()
        self._results: dict[str, AdaptiveLearningResult] = {}
        self._checkpoints: dict[str, AdaptiveCheckpoint] = {}
        self._progress: dict[str, AdaptiveProgress] = {}
        self._submitted: dict[str, tuple[AdaptiveTaskType, dict[str, Any]]] = {}
        self._cancelled: set[str] = set()
        self._stop_event = Event()
        self._pause_event = Event()
        self._idle_mode = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="adaptive-learning-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def set_idle(self, idle: bool) -> None:
        if idle:
            self._idle_mode.set()
        else:
            self._idle_mode.clear()

    def submit_incremental_training(self, evidence_items: list[AdaptiveEvidence], *, idle_only: bool = False) -> str:
        return self._submit(
            task_type=AdaptiveTaskType.INCREMENTAL_TRAIN,
            payload={"evidence_items": list(evidence_items), "idle_only": bool(idle_only)},
        )

    def submit_rollback(self) -> str:
        return self._submit(task_type=AdaptiveTaskType.ROLLBACK, payload={})

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)
        checkpoint = self._checkpoints.get(job_id)
        if checkpoint is not None:
            checkpoint.status = AdaptiveTaskStatus.CANCELLED
            checkpoint.stage = "cancelled"
        progress = self._progress.get(job_id)
        if progress is not None:
            progress.status = AdaptiveTaskStatus.CANCELLED
            progress.message = "cancelled"

    def resume_job(self, job_id: str) -> bool:
        submitted = self._submitted.get(job_id)
        if submitted is None:
            return False
        task_type, payload = submitted
        self._cancelled.discard(job_id)
        self._queue.put((job_id, task_type, payload))
        checkpoint = self._checkpoints[job_id]
        checkpoint.status = AdaptiveTaskStatus.PENDING
        checkpoint.stage = "resumed"
        checkpoint.progress = 0
        checkpoint.processed_events = 0
        self._progress[job_id] = AdaptiveProgress(
            job_id=job_id,
            task_type=task_type,
            status=AdaptiveTaskStatus.PENDING,
            progress=0,
            message="resumed",
        )
        return True

    def checkpoint_for(self, job_id: str) -> AdaptiveCheckpoint | None:
        return self._checkpoints.get(job_id)

    def progress_for(self, job_id: str) -> AdaptiveProgress | None:
        return self._progress.get(job_id)

    def result_for(self, job_id: str) -> AdaptiveLearningResult | None:
        return self._results.get(job_id)

    def _submit(self, *, task_type: AdaptiveTaskType, payload: dict[str, Any]) -> str:
        job_id = str(uuid4())
        self._submitted[job_id] = (task_type, dict(payload))
        self._checkpoints[job_id] = AdaptiveCheckpoint(job_id=job_id, task_type=task_type)
        self._progress[job_id] = AdaptiveProgress(
            job_id=job_id,
            task_type=task_type,
            status=AdaptiveTaskStatus.PENDING,
            progress=0,
            message="queued",
        )
        self._queue.put((job_id, task_type, payload))
        return job_id

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                continue
            try:
                job_id, task_type, payload = self._queue.get(timeout=self._POLL_INTERVAL)
            except Empty:
                continue

            checkpoint = self._checkpoints[job_id]
            progress = self._progress[job_id]

            if payload.get("idle_only") and not self._idle_mode.is_set():
                self._queue.put((job_id, task_type, payload))
                self._queue.task_done()
                continue

            if job_id in self._cancelled:
                checkpoint.status = AdaptiveTaskStatus.CANCELLED
                checkpoint.stage = "cancelled"
                progress.status = AdaptiveTaskStatus.CANCELLED
                progress.message = "cancelled before execution"
                self._queue.task_done()
                continue

            checkpoint.status = AdaptiveTaskStatus.RUNNING
            checkpoint.stage = "running"
            checkpoint.progress = 10
            progress.status = AdaptiveTaskStatus.RUNNING
            progress.progress = 10
            progress.message = "running"

            try:
                result = self._dispatch(job_id=job_id, task_type=task_type, payload=payload)
                if job_id in self._cancelled:
                    checkpoint.status = AdaptiveTaskStatus.CANCELLED
                    checkpoint.stage = "cancelled"
                    checkpoint.progress = 50
                    progress.status = AdaptiveTaskStatus.CANCELLED
                    progress.progress = 50
                    progress.message = "cancelled"
                else:
                    checkpoint.status = AdaptiveTaskStatus.COMPLETED
                    checkpoint.stage = "completed"
                    checkpoint.progress = 100
                    progress.status = AdaptiveTaskStatus.COMPLETED
                    progress.progress = 100
                    progress.message = "completed"
                    self._results[job_id] = result
            except Exception as exc:
                checkpoint.status = AdaptiveTaskStatus.FAILED
                checkpoint.stage = "failed"
                checkpoint.progress = 100
                progress.status = AdaptiveTaskStatus.FAILED
                progress.progress = 100
                progress.message = str(exc)
                self._results[job_id] = AdaptiveLearningResult(action=task_type.value, success=False, message=str(exc))
            finally:
                self._queue.task_done()

    def _dispatch(self, *, job_id: str, task_type: AdaptiveTaskType, payload: dict[str, Any]) -> AdaptiveLearningResult:
        checkpoint = self._checkpoints[job_id]
        progress = self._progress[job_id]
        if task_type == AdaptiveTaskType.INCREMENTAL_TRAIN:
            evidence_items = list(payload.get("evidence_items", []))
            total = max(1, len(evidence_items))
            for index, evidence in enumerate(evidence_items, start=1):
                if job_id in self._cancelled:
                    break
                self.service.ingest_evidence(evidence)
                checkpoint.processed_events = index
                checkpoint.progress = min(95, int((index / float(total)) * 95))
                progress.progress = checkpoint.progress
                progress.message = f"processed {index}/{total}"
            return AdaptiveLearningResult(
                action="incremental_train",
                success=job_id not in self._cancelled,
                details={"processed_events": checkpoint.processed_events, "total_events": len(evidence_items)},
            )

        if task_type == AdaptiveTaskType.ROLLBACK:
            return self.service.rollback()

        raise AdaptiveCheckpointError(f"Unsupported task type: {task_type}")
