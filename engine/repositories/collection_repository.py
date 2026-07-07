from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from engine.collections.collection_builder import CollectionBuilder
from engine.collections.collection_exceptions import CollectionNotFoundError, CollectionValidationError
from engine.collections.collection_models import CollectionKind, CollectionRecord
from engine.database.models.image import Image
from engine.dataset.dataset_builder import DatasetBuilder
from engine.repositories.base_repository import BaseRepository
from engine.repositories.dataset_repository import DatasetRepository


class CollectionRepository(BaseRepository[Image]):
    """Thread-safe repository for collection hierarchy and image membership."""

    _collections: dict[int, CollectionRecord] = {}
    _next_id: int = 1
    _lock = Lock()

    def __init__(self) -> None:
        super().__init__(Image)
        self.builder = CollectionBuilder()

    @classmethod
    def reset_state(cls) -> None:
        with cls._lock:
            cls._collections = {}
            cls._next_id = 1

    def create_collection(
        self,
        *,
        name: str,
        kind: CollectionKind,
        parent_id: int | None = None,
        metadata: dict | None = None,
        smart_rule: dict | None = None,
    ) -> CollectionRecord:
        with self._lock:
            if parent_id is not None and parent_id not in self._collections:
                raise CollectionNotFoundError(f"Parent collection not found: {parent_id}")

            collection_id = self._next_id
            self._next_id += 1
            record = self.builder.build_collection(
                collection_id=collection_id,
                name=name,
                kind=kind,
                parent_id=parent_id,
                metadata=metadata,
                smart_rule=smart_rule,
            )
            self._collections[collection_id] = record
            return record

    def get_collection(self, collection_id: int) -> CollectionRecord | None:
        with self._lock:
            return self._collections.get(collection_id)

    def get_collection_by_name(self, name: str, *, parent_id: int | None = None) -> CollectionRecord | None:
        target = name.strip().lower()
        with self._lock:
            for record in self._collections.values():
                if record.parent_id == parent_id and record.name.strip().lower() == target:
                    return record
        return None

    def get_or_create_collection(
        self,
        *,
        name: str,
        kind: CollectionKind = CollectionKind.STATIC,
        parent_id: int | None = None,
        metadata: dict | None = None,
        smart_rule: dict | None = None,
    ) -> CollectionRecord:
        existing = self.get_collection_by_name(name, parent_id=parent_id)
        if existing is not None:
            return existing
        return self.create_collection(
            name=name,
            kind=kind,
            parent_id=parent_id,
            metadata=metadata,
            smart_rule=smart_rule,
        )

    def list_collections(self) -> list[CollectionRecord]:
        with self._lock:
            return list(self._collections.values())

    def list_children(self, parent_id: int | None) -> list[CollectionRecord]:
        with self._lock:
            return [item for item in self._collections.values() if item.parent_id == parent_id]

    def rename_collection(self, collection_id: int, new_name: str) -> CollectionRecord:
        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            collection.name = new_name
            collection.updated_at = datetime.now(timezone.utc)
            return collection

    def update_collection_metadata(self, collection_id: int, metadata: dict) -> CollectionRecord:
        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            collection.metadata = dict(metadata)
            collection.updated_at = datetime.now(timezone.utc)
            return collection

    def delete_collection(self, collection_id: int) -> list[int]:
        with self._lock:
            if collection_id not in self._collections:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")

            to_delete = self._collect_descendants(collection_id)
            to_delete.append(collection_id)
            deleted: list[int] = []
            for identifier in sorted(set(to_delete), reverse=True):
                if identifier in self._collections:
                    del self._collections[identifier]
                    deleted.append(identifier)
            return deleted

    def set_parent(self, collection_id: int, parent_id: int | None) -> CollectionRecord:
        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            if parent_id is not None and parent_id not in self._collections:
                raise CollectionNotFoundError(f"Parent collection not found: {parent_id}")
            if parent_id == collection_id:
                raise CollectionValidationError("Collection cannot be parent of itself")
            collection.parent_id = parent_id
            collection.updated_at = datetime.now(timezone.utc)
            return collection

    def add_image(self, collection_id: int, image_id: int) -> bool:
        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            if image_id in collection.image_ids:
                return False
            collection.image_ids.add(image_id)
            collection.updated_at = datetime.now(timezone.utc)
            return True

    def remove_image(self, collection_id: int, image_id: int) -> bool:
        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            if image_id not in collection.image_ids:
                return False
            collection.image_ids.remove(image_id)
            collection.updated_at = datetime.now(timezone.utc)
            return True

    def bulk_add_images(self, collection_id: int, image_ids: list[int]) -> list[int]:
        changed: list[int] = []
        for image_id in image_ids:
            if self.add_image(collection_id, image_id):
                changed.append(image_id)
        return changed

    def bulk_remove_images(self, collection_id: int, image_ids: list[int]) -> list[int]:
        changed: list[int] = []
        for image_id in image_ids:
            if self.remove_image(collection_id, image_id):
                changed.append(image_id)
        return changed

    def bulk_move_images(self, source_collection_id: int, target_collection_id: int, image_ids: list[int]) -> list[int]:
        moved: list[int] = []
        for image_id in image_ids:
            removed = self.remove_image(source_collection_id, image_id)
            if not removed:
                continue
            _ = self.add_image(target_collection_id, image_id)
            moved.append(image_id)
        return moved

    def set_thumbnail(self, collection_id: int, thumbnail_path: str | None) -> CollectionRecord:
        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            collection.thumbnail_path = thumbnail_path
            collection.updated_at = datetime.now(timezone.utc)
            return collection

    def get_image_path(self, image_id: int) -> str | None:
        image = self.session.query(Image).filter(Image.id == image_id).first()
        if image is None:
            return None
        return image.original_path

    def refresh_smart_collection(self, collection_id: int) -> list[int]:
        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            if collection.kind != CollectionKind.SMART:
                raise CollectionValidationError("refresh_smart_collection is only valid for smart collections")
            smart_rule = dict(collection.smart_rule)

        dataset_repository = DatasetRepository()
        dataset_builder = DatasetBuilder(dataset_repository)
        matched: list[int] = []

        images = list(self.session.query(Image).all())
        for image in images:
            entry = dataset_builder.build(image.original_path)
            if entry is None:
                continue
            payload = {
                "tags": entry.payload.get("tags", []),
                "confidence_score": entry.confidence_score,
                "quality_score": entry.quality_score,
                "completeness_score": entry.completeness_score,
            }
            if self.builder.matches_smart_rule(payload, smart_rule):
                matched.append(image.id)

        with self._lock:
            collection = self._collections.get(collection_id)
            if collection is None:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            collection.image_ids = set(matched)
            collection.updated_at = datetime.now(timezone.utc)
        return matched

    def _collect_descendants(self, collection_id: int) -> list[int]:
        descendants: list[int] = []
        queue = [collection_id]
        while queue:
            current = queue.pop(0)
            children = [item.collection_id for item in self._collections.values() if item.parent_id == current]
            descendants.extend(children)
            queue.extend(children)
        return descendants

    def descendant_count(self, collection_id: int) -> int:
        with self._lock:
            if collection_id not in self._collections:
                return 0
            return len(set(self._collect_descendants(collection_id)))
