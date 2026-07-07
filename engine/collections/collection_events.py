from __future__ import annotations

from dataclasses import dataclass

from engine.collections.collection_models import CollectionAction


@dataclass(slots=True)
class CollectionStarted:
    action: CollectionAction
    collection_id: int


@dataclass(slots=True)
class CollectionChanged:
    action: CollectionAction
    collection_id: int
    changed: bool
    affected_count: int


@dataclass(slots=True)
class CollectionSkipped:
    action: CollectionAction
    collection_id: int
    reason: str


@dataclass(slots=True)
class CollectionFailed:
    action: CollectionAction
    collection_id: int
    error: str


@dataclass(slots=True)
class CollectionCompleted:
    total: int
    changed: int
    skipped: int
    failed: int
