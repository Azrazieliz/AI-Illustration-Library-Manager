from __future__ import annotations

from threading import Event, Thread

from engine.knowledge_graph.knowledge_graph_models import KnowledgeGraphCheckpoint
from engine.knowledge_graph.knowledge_graph_service import KnowledgeGraphService
from engine.pipeline import PipelineJob, QueueManager, QueueType


class KnowledgeGraphWorker:
    """Background worker that drains the SEARCH queue for graph updates."""

    _POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        service: KnowledgeGraphService | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.service = service or KnowledgeGraphService(queue_manager=self.queue_manager)
        self._checkpoint = KnowledgeGraphCheckpoint()
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="knowledge-graph-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def process_jobs(self, jobs: list[PipelineJob]) -> None:
        self.service.process_knowledge_graph_jobs(jobs, checkpoint=self._checkpoint)

    def _run(self) -> None:
        import time

        while not self._stop_event.is_set():
            job: PipelineJob | None = self.queue_manager.dequeue(QueueType.SEARCH)
            if job is None:
                time.sleep(self._POLL_INTERVAL)
                continue
            stage = (job.metadata or {}).get("stage")
            if stage != "knowledge_graph":
                continue
            self.service.process_knowledge_graph_job(job, checkpoint=self._checkpoint)
