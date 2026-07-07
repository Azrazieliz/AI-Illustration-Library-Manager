from __future__ import annotations

from pathlib import Path

from engine.knowledge_graph.knowledge_graph_engine import KnowledgeGraphEngine
from engine.knowledge_graph.knowledge_graph_models import (
    EdgeType,
    GraphNode,
    GraphPath,
    GraphTraversalResult,
    KnowledgeGraphCheckpoint,
    KnowledgeGraphUpdateResult,
)
from engine.pipeline import PipelineJob, QueueManager, QueueType


class KnowledgeGraphService:
    """Service facade connecting knowledge graph engine to pipeline jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: KnowledgeGraphEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or KnowledgeGraphEngine(callback=self._handle_event)

    def process_knowledge_graph_job(
        self,
        job: PipelineJob,
        *,
        checkpoint: KnowledgeGraphCheckpoint | None = None,
    ) -> KnowledgeGraphUpdateResult | None:
        """Consume semantic-search pipeline job and update graph incrementally."""
        if not job.source_path:
            return None
        result = self.engine.process_path(
            Path(job.source_path),
            checkpoint=checkpoint,
            metadata=job.metadata,
        )
        if result is not None:
            self._publish_tagging_job(job, result)
        return result

    def process_knowledge_graph_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        checkpoint: KnowledgeGraphCheckpoint | None = None,
    ) -> list[KnowledgeGraphUpdateResult]:
        """Process a batch of semantic-search jobs."""
        results: list[KnowledgeGraphUpdateResult] = []
        for job in jobs:
            result = self.process_knowledge_graph_job(job, checkpoint=checkpoint)
            if result is not None:
                results.append(result)
        return results

    def neighbors(self, node_id: str, edge_type: EdgeType | None = None) -> list[GraphNode]:
        return self.engine.neighbors(node_id=node_id, edge_type=edge_type)

    def traverse(self, start_node_id: str, max_depth: int = 1) -> GraphTraversalResult:
        return self.engine.traverse(start_node_id=start_node_id, max_depth=max_depth)

    def shortest_path(self, start_node_id: str, end_node_id: str) -> GraphPath | None:
        return self.engine.shortest_path(start_node_id=start_node_id, end_node_id=end_node_id)

    def _publish_tagging_job(
        self,
        original_job: PipelineJob,
        result: KnowledgeGraphUpdateResult,
    ) -> None:
        tagging_job = PipelineJob(
            source_path=original_job.source_path,
            queue_type=QueueType.SEARCH,
            metadata={
                **(original_job.metadata or {}),
                "stage": "tagging",
                "image_id": result.image_id,
                "graph_nodes": result.created_nodes,
                "graph_edges": result.created_edges,
            },
        )
        self.queue_manager.enqueue(QueueType.SEARCH, tagging_job)

    def _handle_event(self, event: object) -> None:
        return None
