from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable

from engine.android.android_exceptions import AndroidWorkerError
from engine.android.android_models import AndroidJob


ProgressCallback = Callable[[AndroidJob], None]
LowMemoryCallback = Callable[[int], None]


@dataclass(slots=True)
class _WorkRequest:
    action: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class AndroidWorker:
    """Background executor for Android bridge tasks with resumable checkpoints."""

    def __init__(self, *, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="android-worker")
        self._lock = Lock()
        self._futures: dict[str, Future[Any]] = {}
        self._jobs: dict[str, AndroidJob] = {}
        self._checkpoints: dict[str, str] = {}
        self._cancelled: set[str] = set()
        self._requests: dict[str, _WorkRequest] = {}
        self._progress_callbacks: list[ProgressCallback] = []
        self._low_memory_callbacks: list[LowMemoryCallback] = []

    def register_progress_callback(self, callback: ProgressCallback) -> None:
        self._progress_callbacks.append(callback)

    def register_low_memory_callback(self, callback: LowMemoryCallback) -> None:
        self._low_memory_callbacks.append(callback)

    def submit(
        self,
        *,
        job_id: str,
        action: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        checkpoint: str | None = None,
    ) -> AndroidJob:
        payload = kwargs or {}
        request = _WorkRequest(action=action, args=args, kwargs=dict(payload))
        with self._lock:
            if checkpoint is not None:
                self._checkpoints[job_id] = checkpoint
            self._requests[job_id] = request

            job = self._jobs.get(job_id)
            if job is None:
                job = AndroidJob(job_id=job_id)
                self._jobs[job_id] = job
            job.status = "running"
            job.checkpoint = self._checkpoints.get(job_id)
            self._cancelled.discard(job_id)

            future = self._executor.submit(self._execute_job, job_id)
            self._futures[job_id] = future
            return AndroidJob.from_dict(job.to_dict())

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            self._cancelled.add(job_id)
            future = self._futures.get(job_id)
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "cancelled"
            cancelled = bool(future and future.cancel())
        self._emit_progress(job_id, message="cancelled")
        return cancelled or (future is not None)

    def resume(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._requests:
                return False
            request = self._requests[job_id]
        self.submit(job_id=job_id, action=request.action, args=request.args, kwargs=request.kwargs, checkpoint=self._checkpoints.get(job_id))
        self._emit_progress(job_id, message="resumed")
        return True

    def report_progress(self, job_id: str, progress: float, *, message: str = "", checkpoint: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise AndroidWorkerError(f"Unknown job id: {job_id}")
            job.progress = min(100.0, max(0.0, progress))
            if message:
                job.message = message
            if checkpoint is not None:
                self._checkpoints[job_id] = checkpoint
                job.checkpoint = checkpoint
        self._emit_progress(job_id)

    def checkpoint(self, job_id: str) -> str | None:
        with self._lock:
            return self._checkpoints.get(job_id)

    def get_job(self, job_id: str) -> AndroidJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else AndroidJob.from_dict(job.to_dict())

    def running_jobs(self) -> list[AndroidJob]:
        with self._lock:
            return [
                AndroidJob.from_dict(job.to_dict())
                for job in self._jobs.values()
                if job.status == "running"
            ]

    def background_task_count(self) -> int:
        with self._lock:
            return len([job for job in self._jobs.values() if job.status == "running"])

    def on_low_memory(self, level: int) -> None:
        for callback in self._low_memory_callbacks:
            callback(level)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _execute_job(self, job_id: str) -> Any:
        with self._lock:
            request = self._requests.get(job_id)
            if request is None:
                raise AndroidWorkerError(f"Missing request for job {job_id}")
            if job_id in self._cancelled:
                job = self._jobs[job_id]
                job.status = "cancelled"
                return None

        try:
            result = request.action(*request.args, **request.kwargs)
            with self._lock:
                job = self._jobs[job_id]
                if job_id in self._cancelled:
                    job.status = "cancelled"
                else:
                    job.progress = 100.0
                    job.status = "completed"
                    job.message = "completed"
            self._emit_progress(job_id)
            return result
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.message = str(exc)
            self._emit_progress(job_id)
            raise

    def _emit_progress(self, job_id: str, *, message: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if message is not None:
                job.message = message
            snapshot = AndroidJob.from_dict(job.to_dict())
        for callback in self._progress_callbacks:
            callback(snapshot)
