from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from threading import RLock

from sqlalchemy import delete, or_, select

from engine.database.models.knowledge_graph import KnowledgeGraphEdgeRecord, KnowledgeGraphNodeRecord
from engine.database.session import session_scope
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


class DurableKnowledgeGraphBackend(KnowledgeGraphBackend):
    """SQLite-backed materialized graph for runtime traversal and recovery."""

    _lock = RLock()

    @classmethod
    def reset_state(cls) -> None:
        with cls._lock, session_scope() as session:
            session.execute(delete(KnowledgeGraphEdgeRecord))
            session.execute(delete(KnowledgeGraphNodeRecord))

    def upsert_node(self, node: GraphNode) -> bool:
        with self._lock, session_scope() as session:
            row = self._get_node_row(session, node.id)
            if row is None:
                session.add(
                    KnowledgeGraphNodeRecord(
                        node_id=node.id,
                        node_type=node.node_type.value,
                        label=node.label,
                        normalized_label=_normalize(node.label),
                        metadata_payload=dict(node.metadata),
                    )
                )
                return True

            row.node_type = node.node_type.value
            row.label = node.label
            row.normalized_label = _normalize(node.label)
            row.metadata_payload = dict(node.metadata)
            return False

    def upsert_edge(self, edge: GraphEdge) -> bool:
        with self._lock, session_scope() as session:
            if self._get_node_row(session, edge.source_id) is None or self._get_node_row(session, edge.target_id) is None:
                raise KnowledgeGraphBackendError("Edge references unknown node")

            row = session.scalar(
                select(KnowledgeGraphEdgeRecord).where(
                    KnowledgeGraphEdgeRecord.source_node_id == edge.source_id,
                    KnowledgeGraphEdgeRecord.target_node_id == edge.target_id,
                    KnowledgeGraphEdgeRecord.edge_type == edge.edge_type.value,
                )
            )
            if row is None:
                session.add(
                    KnowledgeGraphEdgeRecord(
                        source_node_id=edge.source_id,
                        target_node_id=edge.target_id,
                        edge_type=edge.edge_type.value,
                        confidence=float(edge.confidence),
                        metadata_payload=dict(edge.metadata),
                    )
                )
                return True

            row.confidence = max(float(row.confidence), float(edge.confidence))
            row.metadata_payload = {**dict(row.metadata_payload or {}), **dict(edge.metadata)}
            return False

    def merge_nodes(self, primary_node_id: str, duplicate_node_id: str) -> None:
        with self._lock, session_scope() as session:
            primary = self._get_node_row(session, primary_node_id)
            duplicate = self._get_node_row(session, duplicate_node_id)
            if primary is None or duplicate is None:
                raise KnowledgeGraphBackendError("Cannot merge missing nodes")
            if primary_node_id == duplicate_node_id:
                return

            affected = list(
                session.scalars(
                    select(KnowledgeGraphEdgeRecord).where(
                        or_(
                            KnowledgeGraphEdgeRecord.source_node_id == duplicate_node_id,
                            KnowledgeGraphEdgeRecord.target_node_id == duplicate_node_id,
                        )
                    )
                )
            )
            rewired: dict[tuple[str, str, str], tuple[float, dict]] = {}
            for row in affected:
                source_node_id = primary_node_id if row.source_node_id == duplicate_node_id else row.source_node_id
                target_node_id = primary_node_id if row.target_node_id == duplicate_node_id else row.target_node_id
                if source_node_id == target_node_id:
                    continue
                key = (source_node_id, target_node_id, row.edge_type)
                current = rewired.get(key)
                payload = dict(row.metadata_payload or {})
                if current is None:
                    rewired[key] = (float(row.confidence), payload)
                else:
                    rewired[key] = (max(current[0], float(row.confidence)), {**current[1], **payload})

            for row in affected:
                session.delete(row)
            session.flush()

            for (source_node_id, target_node_id, edge_type), (confidence, metadata) in rewired.items():
                existing = session.scalar(
                    select(KnowledgeGraphEdgeRecord).where(
                        KnowledgeGraphEdgeRecord.source_node_id == source_node_id,
                        KnowledgeGraphEdgeRecord.target_node_id == target_node_id,
                        KnowledgeGraphEdgeRecord.edge_type == edge_type,
                    )
                )
                if existing is None:
                    session.add(
                        KnowledgeGraphEdgeRecord(
                            source_node_id=source_node_id,
                            target_node_id=target_node_id,
                            edge_type=edge_type,
                            confidence=confidence,
                            metadata_payload=metadata,
                        )
                    )
                else:
                    existing.confidence = max(float(existing.confidence), confidence)
                    existing.metadata_payload = {**dict(existing.metadata_payload or {}), **metadata}

            session.delete(duplicate)

    def neighbors(self, node_id: str, edge_type: EdgeType | None = None) -> list[GraphNode]:
        with self._lock, session_scope() as session:
            if self._get_node_row(session, node_id) is None:
                return []
            statement = select(KnowledgeGraphEdgeRecord).where(
                or_(
                    KnowledgeGraphEdgeRecord.source_node_id == node_id,
                    KnowledgeGraphEdgeRecord.target_node_id == node_id,
                )
            ).order_by(KnowledgeGraphEdgeRecord.id)
            if edge_type is not None:
                statement = statement.where(KnowledgeGraphEdgeRecord.edge_type == edge_type.value)
            neighbor_ids: list[str] = []
            seen: set[str] = set()
            for row in session.scalars(statement):
                neighbor_id = row.target_node_id if row.source_node_id == node_id else row.source_node_id
                if neighbor_id not in seen:
                    seen.add(neighbor_id)
                    neighbor_ids.append(neighbor_id)
            if not neighbor_ids:
                return []
            rows = list(
                session.scalars(
                    select(KnowledgeGraphNodeRecord).where(KnowledgeGraphNodeRecord.node_id.in_(neighbor_ids))
                )
            )
            by_id = {row.node_id: row for row in rows}
            return [self._to_node(by_id[neighbor_id]) for neighbor_id in neighbor_ids if neighbor_id in by_id]

    def traverse(self, start_node_id: str, max_depth: int = 1) -> list[str]:
        with self._lock, session_scope() as session:
            if self._get_node_row(session, start_node_id) is None:
                return []
            adjacency = self._adjacency(session)

        visited = {start_node_id}
        ordered = [start_node_id]
        queue: deque[tuple[str, int]] = deque([(start_node_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor_id in adjacency.get(current, []):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                ordered.append(neighbor_id)
                queue.append((neighbor_id, depth + 1))
        return ordered

    def shortest_path(self, start_node_id: str, end_node_id: str) -> GraphPath | None:
        with self._lock, session_scope() as session:
            if self._get_node_row(session, start_node_id) is None or self._get_node_row(session, end_node_id) is None:
                return None
            adjacency = self._adjacency(session)

        queue: deque[str] = deque([start_node_id])
        parent: dict[str, str | None] = {start_node_id: None}
        while queue:
            current = queue.popleft()
            if current == end_node_id:
                break
            for neighbor_id in adjacency.get(current, []):
                if neighbor_id in parent:
                    continue
                parent[neighbor_id] = current
                queue.append(neighbor_id)

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
        with self._lock, session_scope() as session:
            row = session.scalar(
                select(KnowledgeGraphNodeRecord)
                .where(
                    KnowledgeGraphNodeRecord.node_type == node_type.value,
                    KnowledgeGraphNodeRecord.normalized_label == _normalize(label),
                )
                .order_by(KnowledgeGraphNodeRecord.id)
            )
            return None if row is None else self._to_node(row)

    @staticmethod
    def _get_node_row(session, node_id: str) -> KnowledgeGraphNodeRecord | None:
        return session.scalar(select(KnowledgeGraphNodeRecord).where(KnowledgeGraphNodeRecord.node_id == node_id))

    @staticmethod
    def _to_node(row: KnowledgeGraphNodeRecord) -> GraphNode:
        return GraphNode(
            id=row.node_id,
            node_type=NodeType(row.node_type),
            label=row.label,
            metadata=dict(row.metadata_payload or {}),
        )

    @staticmethod
    def _adjacency(session) -> dict[str, list[str]]:
        adjacency: dict[str, list[str]] = {}
        for row in session.scalars(select(KnowledgeGraphEdgeRecord).order_by(KnowledgeGraphEdgeRecord.id)):
            adjacency.setdefault(row.source_node_id, []).append(row.target_node_id)
            adjacency.setdefault(row.target_node_id, []).append(row.source_node_id)
        return adjacency


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())
