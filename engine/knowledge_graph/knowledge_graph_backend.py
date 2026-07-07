from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

from engine.knowledge_graph.knowledge_graph_exceptions import KnowledgeGraphBackendError
from engine.knowledge_graph.knowledge_graph_models import EdgeType, GraphEdge, GraphNode, GraphPath, NodeType


class KnowledgeGraphBackend(ABC):
    """Abstract backend interface for graph databases."""

    @abstractmethod
    def upsert_node(self, node: GraphNode) -> bool:
        """Insert or update node. Returns True when created."""

    @abstractmethod
    def upsert_edge(self, edge: GraphEdge) -> bool:
        """Insert or update edge. Returns True when created."""

    @abstractmethod
    def merge_nodes(self, primary_node_id: str, duplicate_node_id: str) -> None:
        """Merge duplicate node into primary node."""

    @abstractmethod
    def neighbors(self, node_id: str, edge_type: EdgeType | None = None) -> list[GraphNode]:
        """Return neighbor nodes for one node."""

    @abstractmethod
    def traverse(self, start_node_id: str, max_depth: int = 1) -> list[str]:
        """Return visited node ids by BFS traversal."""

    @abstractmethod
    def shortest_path(self, start_node_id: str, end_node_id: str) -> GraphPath | None:
        """Return shortest path between two nodes."""

    @abstractmethod
    def find_node_by_type_label(self, node_type: NodeType, label: str) -> GraphNode | None:
        """Return existing node with same type and label if present."""


class InMemoryKnowledgeGraphBackend(KnowledgeGraphBackend):
    """In-memory backend used for tests and local execution."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[tuple[str, str, str], GraphEdge] = {}

    def upsert_node(self, node: GraphNode) -> bool:
        created = node.id not in self._nodes
        self._nodes[node.id] = node
        return created

    def upsert_edge(self, edge: GraphEdge) -> bool:
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            raise KnowledgeGraphBackendError("Edge references unknown node")

        key = (edge.source_id, edge.target_id, edge.edge_type.value)
        existing = self._edges.get(key)
        created = existing is None
        if existing is None:
            self._edges[key] = edge
        else:
            self._edges[key] = GraphEdge(
                source_id=edge.source_id,
                target_id=edge.target_id,
                edge_type=edge.edge_type,
                confidence=max(existing.confidence, edge.confidence),
                metadata={**existing.metadata, **edge.metadata},
            )
        return created

    def merge_nodes(self, primary_node_id: str, duplicate_node_id: str) -> None:
        if primary_node_id not in self._nodes or duplicate_node_id not in self._nodes:
            raise KnowledgeGraphBackendError("Cannot merge missing nodes")
        if primary_node_id == duplicate_node_id:
            return

        rewired: dict[tuple[str, str, str], GraphEdge] = {}
        for edge in self._edges.values():
            source_id = primary_node_id if edge.source_id == duplicate_node_id else edge.source_id
            target_id = primary_node_id if edge.target_id == duplicate_node_id else edge.target_id
            if source_id == target_id:
                continue
            key = (source_id, target_id, edge.edge_type.value)
            current = rewired.get(key)
            if current is None:
                rewired[key] = GraphEdge(
                    source_id=source_id,
                    target_id=target_id,
                    edge_type=edge.edge_type,
                    confidence=edge.confidence,
                    metadata=dict(edge.metadata),
                )
            else:
                current.confidence = max(current.confidence, edge.confidence)
                current.metadata.update(edge.metadata)

        self._edges = rewired
        del self._nodes[duplicate_node_id]

    def neighbors(self, node_id: str, edge_type: EdgeType | None = None) -> list[GraphNode]:
        if node_id not in self._nodes:
            return []

        result: list[GraphNode] = []
        seen: set[str] = set()
        for edge in self._edges.values():
            if edge_type is not None and edge.edge_type != edge_type:
                continue

            neighbor_id: str | None = None
            if edge.source_id == node_id:
                neighbor_id = edge.target_id
            elif edge.target_id == node_id:
                neighbor_id = edge.source_id

            if neighbor_id is None or neighbor_id in seen:
                continue
            seen.add(neighbor_id)
            result.append(self._nodes[neighbor_id])

        return result

    def traverse(self, start_node_id: str, max_depth: int = 1) -> list[str]:
        if start_node_id not in self._nodes:
            return []

        visited: set[str] = {start_node_id}
        queue: deque[tuple[str, int]] = deque([(start_node_id, 0)])

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor in self.neighbors(current):
                if neighbor.id in visited:
                    continue
                visited.add(neighbor.id)
                queue.append((neighbor.id, depth + 1))

        return list(visited)

    def shortest_path(self, start_node_id: str, end_node_id: str) -> GraphPath | None:
        if start_node_id not in self._nodes or end_node_id not in self._nodes:
            return None

        queue: deque[str] = deque([start_node_id])
        parent: dict[str, str | None] = {start_node_id: None}

        while queue:
            current = queue.popleft()
            if current == end_node_id:
                break
            for neighbor in self.neighbors(current):
                if neighbor.id in parent:
                    continue
                parent[neighbor.id] = current
                queue.append(neighbor.id)

        if end_node_id not in parent:
            return None

        path: list[str] = []
        cursor: str | None = end_node_id
        while cursor is not None:
            path.append(cursor)
            cursor = parent[cursor]
        path.reverse()

        return GraphPath(node_ids=path, edge_count=max(0, len(path) - 1))

    def find_node_by_type_label(self, node_type: NodeType, label: str) -> GraphNode | None:
        normalized = _normalize(label)
        for node in self._nodes.values():
            if node.node_type == node_type and _normalize(node.label) == normalized:
                return node
        return None


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())
