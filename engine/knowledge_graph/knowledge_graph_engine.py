from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from engine.knowledge_graph.knowledge_graph_backend import (
    InMemoryKnowledgeGraphBackend,
    KnowledgeGraphBackend,
)
from engine.knowledge_graph.knowledge_graph_builder import KnowledgeGraphBuilder
from engine.knowledge_graph.knowledge_graph_events import (
    KnowledgeGraphBatchCompleted,
    KnowledgeGraphBuildFailed,
    KnowledgeGraphBuildSkipped,
    KnowledgeGraphBuildStarted,
    KnowledgeGraphUpdated,
)
from engine.knowledge_graph.knowledge_graph_exceptions import (
    KnowledgeGraphBuildError,
    KnowledgeGraphQueryError,
)
from engine.knowledge_graph.knowledge_graph_models import (
    EdgeType,
    GraphNode,
    GraphPath,
    GraphTraversalResult,
    KnowledgeGraphCheckpoint,
    KnowledgeGraphUpdateResult,
)
from engine.knowledge_graph.knowledge_graph_statistics import KnowledgeGraphStatistics
from engine.logging import get_logger
from engine.repositories.knowledge_graph_repository import KnowledgeGraphRepository


class KnowledgeGraphEngine:
    """Orchestrates typed knowledge graph construction and query APIs."""

    def __init__(
        self,
        *,
        repository: KnowledgeGraphRepository | None = None,
        backend: KnowledgeGraphBackend | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.repository = repository or KnowledgeGraphRepository()
        self.backend = backend or InMemoryKnowledgeGraphBackend()
        self.builder = KnowledgeGraphBuilder(self.backend)
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = KnowledgeGraphStatistics()

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: KnowledgeGraphCheckpoint | None = None,
        metadata: dict | None = None,
    ) -> list[KnowledgeGraphUpdateResult]:
        """Build graph updates for multiple paths in parallel."""
        self.statistics = KnowledgeGraphStatistics()
        self.statistics.start()
        results: list[KnowledgeGraphUpdateResult] = []
        resolved_paths = [str(Path(path).resolve()) for path in paths]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_one, path, checkpoint, metadata): path
                for path in resolved_paths
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)

        self.statistics.finish()
        self._emit(
            KnowledgeGraphBatchCompleted(
                total=self.statistics.processed,
                updated=self.statistics.updated,
                skipped=self.statistics.skipped,
                failed=self.statistics.failed,
            )
        )
        return results

    def process_path(
        self,
        path: Path | str,
        *,
        checkpoint: KnowledgeGraphCheckpoint | None = None,
        metadata: dict | None = None,
    ) -> KnowledgeGraphUpdateResult | None:
        """Build graph update for a single path."""
        return self._process_one(str(Path(path).resolve()), checkpoint, metadata)

    def neighbors(self, node_id: str, edge_type: EdgeType | None = None) -> list[GraphNode]:
        """Return neighbors of a graph node."""
        try:
            return self.backend.neighbors(node_id, edge_type=edge_type)
        except Exception as e:
            raise KnowledgeGraphQueryError(str(e)) from e

    def traverse(self, start_node_id: str, max_depth: int = 1) -> GraphTraversalResult:
        """Traverse graph from node using BFS up to max depth."""
        try:
            visited = self.backend.traverse(start_node_id=start_node_id, max_depth=max_depth)
        except Exception as e:
            raise KnowledgeGraphQueryError(str(e)) from e
        return GraphTraversalResult(start_node_id=start_node_id, visited_node_ids=visited)

    def shortest_path(self, start_node_id: str, end_node_id: str) -> GraphPath | None:
        """Find shortest path between two nodes."""
        try:
            return self.backend.shortest_path(start_node_id=start_node_id, end_node_id=end_node_id)
        except Exception as e:
            raise KnowledgeGraphQueryError(str(e)) from e

    def _process_one(
        self,
        path: str,
        checkpoint: KnowledgeGraphCheckpoint | None,
        metadata: dict | None,
    ) -> KnowledgeGraphUpdateResult | None:
        resolved = Path(path)

        if checkpoint is not None and checkpoint.is_processed(path):
            self.statistics.increment_processed()
            self.statistics.increment_skipped()
            self._emit(KnowledgeGraphBuildSkipped(path=resolved, reason="Already processed"))
            return None

        self.statistics.increment_processed()
        self._emit(KnowledgeGraphBuildStarted(path=resolved))

        try:
            repository = KnowledgeGraphRepository()
            context = repository.build_image_context(path, metadata=metadata)
            if context is None:
                self.statistics.increment_skipped()
                self._emit(KnowledgeGraphBuildSkipped(path=resolved, reason="Image not found"))
                return None

            created_nodes, created_edges = self.builder.build_from_context(context)

            if checkpoint is not None:
                checkpoint.add_processed(path)

            self.statistics.increment_updated()
            self._emit(
                KnowledgeGraphUpdated(
                    path=resolved,
                    image_id=context.image.id,
                    created_nodes=created_nodes,
                    created_edges=created_edges,
                )
            )
            return KnowledgeGraphUpdateResult(
                image_id=context.image.id,
                path=resolved,
                created_nodes=created_nodes,
                created_edges=created_edges,
            )

        except Exception as e:
            self.statistics.increment_failed()
            self._emit(KnowledgeGraphBuildFailed(path=resolved, error=str(e)))
            return None

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
