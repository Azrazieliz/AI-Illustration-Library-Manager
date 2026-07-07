from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any, Callable
from uuid import uuid4


@dataclass(slots=True)
class BackgroundTaskSnapshot:
    task_id: str
    name: str
    progress: int = 0
    done: bool = False
    cancelled: bool = False
    error: str | None = None
    result: Any = None


@dataclass(slots=True)
class BackgroundTaskContext:
    task_id: str
    cancel_event: Event
    report_progress: Callable[[int], None]

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()


@dataclass(slots=True)
class _TaskState:
    snapshot: BackgroundTaskSnapshot
    cancel_event: Event = field(default_factory=Event)
    future: Future | None = None


class BackgroundTaskManager:
    def __init__(self, *, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ui-bg")
        self._lock = Lock()
        self._tasks: dict[str, _TaskState] = {}

    def submit(self, name: str, work: Callable[[BackgroundTaskContext], Any]) -> str:
        task_id = str(uuid4())
        state = _TaskState(snapshot=BackgroundTaskSnapshot(task_id=task_id, name=name))

        def _run() -> Any:
            context = BackgroundTaskContext(
                task_id=task_id,
                cancel_event=state.cancel_event,
                report_progress=lambda value: self._set_progress(task_id, value),
            )
            return work(context)

        future = self._executor.submit(_run)
        state.future = future

        with self._lock:
            self._tasks[task_id] = state

        def _finalize(done_future: Future) -> None:
            with self._lock:
                current = self._tasks.get(task_id)
                if current is None:
                    return
                current.snapshot.done = True
                current.snapshot.cancelled = current.cancel_event.is_set()
                try:
                    current.snapshot.result = done_future.result()
                except Exception as exc:  # pragma: no cover - defensive
                    current.snapshot.error = str(exc)

        future.add_done_callback(_finalize)
        return task_id

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return False
            state.cancel_event.set()
            state.snapshot.cancelled = True
            return True

    def snapshot(self, task_id: str) -> BackgroundTaskSnapshot | None:
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return None
            return BackgroundTaskSnapshot(
                task_id=state.snapshot.task_id,
                name=state.snapshot.name,
                progress=state.snapshot.progress,
                done=state.snapshot.done,
                cancelled=state.snapshot.cancelled,
                error=state.snapshot.error,
                result=state.snapshot.result,
            )

    def all_snapshots(self) -> list[BackgroundTaskSnapshot]:
        with self._lock:
            return [
                BackgroundTaskSnapshot(
                    task_id=state.snapshot.task_id,
                    name=state.snapshot.name,
                    progress=state.snapshot.progress,
                    done=state.snapshot.done,
                    cancelled=state.snapshot.cancelled,
                    error=state.snapshot.error,
                    result=state.snapshot.result,
                )
                for state in self._tasks.values()
            ]

    def shutdown(self) -> None:
        with self._lock:
            task_ids = list(self._tasks.keys())
        for task_id in task_ids:
            self.cancel(task_id)
        self._executor.shutdown(wait=True)

    def _set_progress(self, task_id: str, progress: int) -> None:
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return
            state.snapshot.progress = max(0, min(100, int(progress)))
