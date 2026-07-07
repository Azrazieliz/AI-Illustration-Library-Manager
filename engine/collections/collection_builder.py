from __future__ import annotations

from datetime import datetime, timezone

from engine.collections.collection_models import (
    CollectionHierarchyNode,
    CollectionKind,
    CollectionRecord,
    CollectionSummary,
)


class CollectionBuilder:
    """Builds collection records, hierarchy views, and derived statistics."""

    def build_collection(
        self,
        *,
        collection_id: int,
        name: str,
        kind: CollectionKind,
        parent_id: int | None,
        metadata: dict | None = None,
        smart_rule: dict | None = None,
    ) -> CollectionRecord:
        now = datetime.now(timezone.utc)
        return CollectionRecord(
            collection_id=collection_id,
            name=name,
            kind=kind,
            parent_id=parent_id,
            metadata=dict(metadata or {}),
            smart_rule=dict(smart_rule or {}),
            created_at=now,
            updated_at=now,
        )

    def build_summary(
        self,
        record: CollectionRecord,
        *,
        child_count: int,
        descendant_count: int,
    ) -> CollectionSummary:
        return CollectionSummary(
            collection_id=record.collection_id,
            name=record.name,
            kind=record.kind,
            parent_id=record.parent_id,
            image_count=len(record.image_ids),
            child_count=child_count,
            descendant_count=descendant_count,
            thumbnail_path=record.thumbnail_path,
        )

    def build_hierarchy_node(self, record: CollectionRecord, children: list[CollectionHierarchyNode]) -> CollectionHierarchyNode:
        return CollectionHierarchyNode(
            collection_id=record.collection_id,
            name=record.name,
            kind=record.kind,
            children=children,
        )

    def choose_thumbnail_path(self, image_paths: list[str]) -> str | None:
        if not image_paths:
            return None
        return image_paths[0]

    def matches_smart_rule(self, payload: dict, smart_rule: dict) -> bool:
        tags_payload = payload.get("tags", [])
        tags = {
            str(item.get("name", "")).strip().lower()
            for item in tags_payload
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        }

        include_tags = {
            str(tag).strip().lower()
            for tag in smart_rule.get("include_tags", [])
            if str(tag).strip()
        }
        exclude_tags = {
            str(tag).strip().lower()
            for tag in smart_rule.get("exclude_tags", [])
            if str(tag).strip()
        }

        if include_tags and tags.isdisjoint(include_tags):
            return False

        if exclude_tags and tags.intersection(exclude_tags):
            return False

        confidence = float(payload.get("confidence_score", 0.0))
        quality = float(payload.get("quality_score", 0.0))
        completeness = float(payload.get("completeness_score", 0.0))

        if confidence < float(smart_rule.get("min_confidence", 0.0)):
            return False

        if quality < float(smart_rule.get("min_quality", 0.0)):
            return False

        if completeness < float(smart_rule.get("min_completeness", 0.0)):
            return False

        return True
