from __future__ import annotations

from pathlib import Path

from engine.knowledge_graph.knowledge_graph_backend import KnowledgeGraphBackend
from engine.knowledge_graph.knowledge_graph_models import EdgeType, GraphEdge, GraphNode, NodeType
from engine.repositories.knowledge_graph_repository import KnowledgeGraphImageContext


class KnowledgeGraphBuilder:
    """Builds typed nodes and edges for one image context."""

    def __init__(self, backend: KnowledgeGraphBackend) -> None:
        self.backend = backend

    def build_from_context(self, context: KnowledgeGraphImageContext) -> tuple[int, int]:
        created_nodes = 0
        created_edges = 0

        image_node = GraphNode(
            id=f"image:{context.image.id}",
            node_type=NodeType.IMAGE,
            label=context.image.filename,
            metadata={
                "image_id": context.image.id,
                "path": context.image.original_path,
            },
        )
        if self.backend.upsert_node(image_node):
            created_nodes += 1

        # Series relationship
        if context.image.series is not None:
            series_node = self._upsert_deduped_node(
                node_type=NodeType.SERIES,
                label=context.image.series.name,
                fallback_id=f"series:{context.image.series.id}",
                metadata={"series_id": context.image.series.id},
            )
            if series_node[1]:
                created_nodes += 1
            if self.backend.upsert_edge(
                GraphEdge(
                    source_id=image_node.id,
                    target_id=series_node[0].id,
                    edge_type=EdgeType.BELONGS_TO_SERIES,
                    confidence=1.0,
                )
            ):
                created_edges += 1

        # Character relationships
        for character in context.image.characters:
            character_node, created = self._upsert_deduped_node(
                node_type=NodeType.CHARACTER,
                label=character.name,
                fallback_id=f"character:{character.id}",
                metadata={"character_id": character.id},
            )
            if created:
                created_nodes += 1
            if self.backend.upsert_edge(
                GraphEdge(
                    source_id=image_node.id,
                    target_id=character_node.id,
                    edge_type=EdgeType.HAS_CHARACTER,
                    confidence=0.95,
                )
            ):
                created_edges += 1

        # Tag relationships
        for tag in context.image.tags:
            tag_node, created = self._upsert_deduped_node(
                node_type=NodeType.TAG,
                label=tag.name,
                fallback_id=f"tag:{tag.id}",
                metadata={"tag_id": tag.id, "category": tag.category},
            )
            if created:
                created_nodes += 1
            if self.backend.upsert_edge(
                GraphEdge(
                    source_id=image_node.id,
                    target_id=tag_node.id,
                    edge_type=EdgeType.TAGGED_WITH,
                    confidence=0.9,
                )
            ):
                created_edges += 1

        # Artist relationships
        for artist in context.artists:
            artist_slug = _slug(artist)
            artist_node, created = self._upsert_deduped_node(
                node_type=NodeType.ARTIST,
                label=artist,
                fallback_id=f"artist:{artist_slug}",
                metadata={"artist": artist},
            )
            if created:
                created_nodes += 1
            if self.backend.upsert_edge(
                GraphEdge(
                    source_id=image_node.id,
                    target_id=artist_node.id,
                    edge_type=EdgeType.CREATED_BY_ARTIST,
                    confidence=0.85,
                )
            ):
                created_edges += 1

        # Embedding relationship
        if context.embedding is not None:
            embedding_node = GraphNode(
                id=f"embedding:{context.embedding.image_id}:{context.embedding.model_name}",
                node_type=NodeType.EMBEDDING,
                label=context.embedding.model_name,
                metadata={
                    "image_id": context.embedding.image_id,
                    "model_version": context.embedding.model_version,
                    "vector_path": context.embedding.vector_path,
                },
            )
            if self.backend.upsert_node(embedding_node):
                created_nodes += 1
            if self.backend.upsert_edge(
                GraphEdge(
                    source_id=image_node.id,
                    target_id=embedding_node.id,
                    edge_type=EdgeType.HAS_EMBEDDING,
                    confidence=1.0,
                )
            ):
                created_edges += 1

        # Duplicate-group relationships
        for record in context.duplicates:
            group_key = f"duplicate-group:{record.image_a_id}:{record.image_b_id}"
            group_node = GraphNode(
                id=group_key,
                node_type=NodeType.DUPLICATE_GROUP,
                label=f"group-{record.image_a_id}-{record.image_b_id}",
                metadata={
                    "match_type": record.match_type,
                    "confidence": record.confidence,
                    "overall_score": record.overall_score,
                },
            )
            if self.backend.upsert_node(group_node):
                created_nodes += 1
            if self.backend.upsert_edge(
                GraphEdge(
                    source_id=image_node.id,
                    target_id=group_node.id,
                    edge_type=EdgeType.IN_DUPLICATE_GROUP,
                    confidence=float(record.overall_score),
                )
            ):
                created_edges += 1

        return created_nodes, created_edges

    def _upsert_deduped_node(
        self,
        *,
        node_type: NodeType,
        label: str,
        fallback_id: str,
        metadata: dict,
    ) -> tuple[GraphNode, bool]:
        existing = self.backend.find_node_by_type_label(node_type, label)
        incoming = GraphNode(
            id=fallback_id,
            node_type=node_type,
            label=label,
            metadata=metadata,
        )
        if existing is None:
            created = self.backend.upsert_node(incoming)
            return incoming, created

        if existing.id != incoming.id:
            self.backend.upsert_node(incoming)
            self.backend.merge_nodes(existing.id, incoming.id)
        return existing, False


def _slug(value: str) -> str:
    lowered = value.strip().lower().replace("_", " ").replace("-", " ")
    return "-".join(lowered.split()) or "unknown"
