from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class CollectionKind(str, Enum):
    STATIC = "static"
    SMART = "smart"


class CollectionAction(str, Enum):
    CREATE = "create"
    RENAME = "rename"
    DELETE = "delete"
    ADD_IMAGE = "add_image"
    REMOVE_IMAGE = "remove_image"
    BULK_ADD = "bulk_add"
    BULK_REMOVE = "bulk_remove"
    BULK_MOVE = "bulk_move"
    REFRESH_SMART = "refresh_smart"
    UPDATE_METADATA = "update_metadata"


@dataclass(slots=True)
class CollectionRecord:
    collection_id: int
    name: str
    kind: CollectionKind
    parent_id: int | None = None
    image_ids: set[int] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    smart_rule: dict[str, Any] = field(default_factory=dict)
    thumbnail_path: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class CollectionOperationResult:
    action: CollectionAction
    collection_id: int
    changed: bool
    affected_image_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class CollectionSummary:
    collection_id: int
    name: str
    kind: CollectionKind
    parent_id: int | None
    image_count: int
    child_count: int
    descendant_count: int
    thumbnail_path: str | None


@dataclass(slots=True)
class CollectionCheckpoint:
    processed_keys: set[str] = field(default_factory=set)

    def _key(self, action: CollectionAction, collection_id: int, image_id: int | None = None) -> str:
        image_part = "*" if image_id is None else str(image_id)
        return f"{action.value}:{collection_id}:{image_part}"

    def add_processed(self, action: CollectionAction, collection_id: int, image_id: int | None = None) -> None:
        self.processed_keys.add(self._key(action, collection_id, image_id))

    def is_processed(self, action: CollectionAction, collection_id: int, image_id: int | None = None) -> bool:
        return self._key(action, collection_id, image_id) in self.processed_keys


@dataclass(slots=True)
class CollectionHierarchyNode:
    collection_id: int
    name: str
    kind: CollectionKind
    children: list[CollectionHierarchyNode] = field(default_factory=list)


@dataclass(slots=True)
class CollectionJobPayload:
    action: CollectionAction
    collection_id: int | None = None
    name: str | None = None
    new_name: str | None = None
    kind: CollectionKind = CollectionKind.STATIC
    parent_id: int | None = None
    image_id: int | None = None
    image_ids: list[int] = field(default_factory=list)
    source_collection_id: int | None = None
    target_collection_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    smart_rule: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> CollectionJobPayload:
        payload = metadata or {}
        raw_action = str(payload.get("collection_action", CollectionAction.ADD_IMAGE.value)).strip().lower()
        try:
            action = CollectionAction(raw_action)
        except ValueError:
            action = CollectionAction.ADD_IMAGE

        raw_kind = str(payload.get("collection_kind", CollectionKind.STATIC.value)).strip().lower()
        try:
            kind = CollectionKind(raw_kind)
        except ValueError:
            kind = CollectionKind.STATIC

        image_ids_raw = payload.get("image_ids", [])
        image_ids: list[int] = []
        if isinstance(image_ids_raw, list):
            for item in image_ids_raw:
                if isinstance(item, int):
                    image_ids.append(item)
                elif isinstance(item, str) and item.isdigit():
                    image_ids.append(int(item))

        collection_id = payload.get("collection_id")
        if isinstance(collection_id, str) and collection_id.isdigit():
            collection_id = int(collection_id)

        image_id = payload.get("image_id")
        if isinstance(image_id, str) and image_id.isdigit():
            image_id = int(image_id)

        parent_id = payload.get("parent_id")
        if isinstance(parent_id, str) and parent_id.isdigit():
            parent_id = int(parent_id)

        source_collection_id = payload.get("source_collection_id")
        if isinstance(source_collection_id, str) and source_collection_id.isdigit():
            source_collection_id = int(source_collection_id)

        target_collection_id = payload.get("target_collection_id")
        if isinstance(target_collection_id, str) and target_collection_id.isdigit():
            target_collection_id = int(target_collection_id)

        return cls(
            action=action,
            collection_id=collection_id if isinstance(collection_id, int) else None,
            name=payload.get("collection_name") if isinstance(payload.get("collection_name"), str) else None,
            new_name=payload.get("new_name") if isinstance(payload.get("new_name"), str) else None,
            kind=kind,
            parent_id=parent_id if isinstance(parent_id, int) else None,
            image_id=image_id if isinstance(image_id, int) else None,
            image_ids=image_ids,
            source_collection_id=source_collection_id if isinstance(source_collection_id, int) else None,
            target_collection_id=target_collection_id if isinstance(target_collection_id, int) else None,
            metadata=payload.get("collection_metadata", {}) if isinstance(payload.get("collection_metadata"), dict) else {},
            smart_rule=payload.get("smart_rule", {}) if isinstance(payload.get("smart_rule"), dict) else {},
        )
