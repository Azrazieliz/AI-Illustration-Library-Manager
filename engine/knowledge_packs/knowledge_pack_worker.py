from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from engine.knowledge_packs.knowledge_pack_exceptions import KnowledgePackWorkerError
from engine.knowledge_packs.knowledge_pack_models import (
    KnowledgePackCheckpoint,
    KnowledgePackManifest,
    KnowledgePackOperationResult,
    KnowledgePackProgress,
    KnowledgePackTaskStatus,
    KnowledgePackTaskType,
)
from engine.knowledge_packs.knowledge_pack_service import KnowledgePackService


class KnowledgePackWorker:
    """Background worker for install/update/uninstall/rollback operations."""

    _POLL_INTERVAL: float = 0.05

    def __init__(self, *, service: KnowledgePackService | None = None) -> None:
        self.service = service or KnowledgePackService()
        self._queue: Queue[tuple[str, KnowledgePackTaskType, dict[str, Any]]] = Queue()
        self._results: dict[str, KnowledgePackOperationResult] = {}
        self._checkpoints: dict[str, KnowledgePackCheckpoint] = {}
        self._progress: dict[str, KnowledgePackProgress] = {}
        self._submitted: dict[str, tuple[KnowledgePackTaskType, dict[str, Any]]] = {}
        self._cancelled: set[str] = set()
        self._stop_event = Event()
        self._pause_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="knowledge-pack-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def submit_install(self, manifest: KnowledgePackManifest) -> str:
        return self._submit(KnowledgePackTaskType.INSTALL, {"manifest": manifest})

    def submit_update(self, manifest: KnowledgePackManifest) -> str:
        return self._submit(KnowledgePackTaskType.UPDATE, {"manifest": manifest})

    def submit_uninstall(self, pack_id: str) -> str:
        return self._submit(KnowledgePackTaskType.UNINSTALL, {"pack_id": pack_id})

    def submit_rollback(self, pack_id: str) -> str:
        return self._submit(KnowledgePackTaskType.ROLLBACK, {"pack_id": pack_id})

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)
        checkpoint = self._checkpoints.get(job_id)
        if checkpoint is not None:
            checkpoint.status = KnowledgePackTaskStatus.CANCELLED
            checkpoint.stage = "cancelled"
            checkpoint.progress = max(checkpoint.progress, 0)
        progress = self._progress.get(job_id)
        if progress is not None:
            progress.status = KnowledgePackTaskStatus.CANCELLED
            progress.message = "cancelled"

    def resume_job(self, job_id: str) -> bool:
        submitted = self._submitted.get(job_id)
        if submitted is None:
            return False
        task_type, payload = submitted
        self._cancelled.discard(job_id)
        self._queue.put((job_id, task_type, payload))
        checkpoint = self._checkpoints[job_id]
        checkpoint.status = KnowledgePackTaskStatus.PENDING
        checkpoint.stage = "resumed"
        checkpoint.progress = 0
        self._progress[job_id] = KnowledgePackProgress(
            job_id=job_id,
            task_type=task_type,
            status=KnowledgePackTaskStatus.PENDING,
            progress=0,
            message="resumed",
        )
        return True

    def result_for(self, job_id: str) -> KnowledgePackOperationResult | None:
        return self._results.get(job_id)

    def checkpoint_for(self, job_id: str) -> KnowledgePackCheckpoint | None:
        return self._checkpoints.get(job_id)

    def progress_for(self, job_id: str) -> KnowledgePackProgress | None:
        return self._progress.get(job_id)

    def _submit(self, task_type: KnowledgePackTaskType, payload: dict[str, Any]) -> str:
        job_id = str(uuid4())
        self._submitted[job_id] = (task_type, dict(payload))
        checkpoint = KnowledgePackCheckpoint(job_id=job_id, task_type=task_type)
        self._checkpoints[job_id] = checkpoint
        self._progress[job_id] = KnowledgePackProgress(
            job_id=job_id,
            task_type=task_type,
            status=KnowledgePackTaskStatus.PENDING,
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

            if job_id in self._cancelled:
                checkpoint.status = KnowledgePackTaskStatus.CANCELLED
                checkpoint.stage = "cancelled"
                checkpoint.progress = 0
                progress.status = KnowledgePackTaskStatus.CANCELLED
                progress.progress = 0
                progress.message = "cancelled before execution"
                self._queue.task_done()
                continue

            checkpoint.status = KnowledgePackTaskStatus.RUNNING
            checkpoint.stage = "running"
            checkpoint.progress = 10
            progress.status = KnowledgePackTaskStatus.RUNNING
            progress.progress = 10
            progress.message = "running"

            try:
                result = self._dispatch(task_type=task_type, payload=payload)
                if job_id in self._cancelled:
                    checkpoint.status = KnowledgePackTaskStatus.CANCELLED
                    checkpoint.stage = "cancelled"
                    checkpoint.progress = 50
                    progress.status = KnowledgePackTaskStatus.CANCELLED
                    progress.progress = 50
                    progress.message = "cancelled"
                else:
                    checkpoint.status = KnowledgePackTaskStatus.COMPLETED
                    checkpoint.stage = "completed"
                    checkpoint.progress = 100
                    progress.status = KnowledgePackTaskStatus.COMPLETED
                    progress.progress = 100
                    progress.message = "completed"
                    self._results[job_id] = result
            except Exception as exc:  # pragma: no cover - defensive path
                checkpoint.status = KnowledgePackTaskStatus.FAILED
                checkpoint.stage = "failed"
                checkpoint.progress = 100
                progress.status = KnowledgePackTaskStatus.FAILED
                progress.progress = 100
                progress.message = str(exc)
                self._results[job_id] = KnowledgePackOperationResult(
                    action=task_type.value,
                    pack_id=str(payload.get("pack_id") or getattr(payload.get("manifest"), "pack_id", "unknown")),
                    success=False,
                    message=str(exc),
                )
            finally:
                self._queue.task_done()

    def _dispatch(self, *, task_type: KnowledgePackTaskType, payload: dict[str, Any]) -> KnowledgePackOperationResult:
        if task_type == KnowledgePackTaskType.INSTALL:
            return self.service.install_pack(payload["manifest"])
        if task_type == KnowledgePackTaskType.UPDATE:
            return self.service.update_pack(payload["manifest"])
        if task_type == KnowledgePackTaskType.UNINSTALL:
            return self.service.uninstall_pack(str(payload["pack_id"]))
        if task_type == KnowledgePackTaskType.ROLLBACK:
            return self.service.rollback_pack(str(payload["pack_id"]))
        raise KnowledgePackWorkerError(f"Unsupported worker task: {task_type}")
