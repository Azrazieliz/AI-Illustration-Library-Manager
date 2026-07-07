from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from engine.collections.collection_builder import CollectionBuilder
from engine.collections.collection_events import (
    CollectionChanged,
    CollectionCompleted,
    CollectionFailed,
    CollectionSkipped,
    CollectionStarted,
)
from engine.collections.collection_models import (
    CollectionAction,
    CollectionCheckpoint,
    CollectionExportBundle,
    CollectionHierarchyNode,
    CollectionJobPayload,
    CollectionKind,
    CollectionSearchResult,
    CollectionOperationResult,
    CollectionSummary,
)
from engine.collections.collection_statistics import CollectionStatistics
from engine.logging import get_logger
from engine.repositories.collection_repository import CollectionRepository


class CollectionEngine:
    """Orchestrates static and smart collection management operations."""

    def __init__(
        self,
        *,
        repository: CollectionRepository | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.repository = repository or CollectionRepository()
        self.builder = CollectionBuilder()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = CollectionStatistics()

    def create_collection(
        self,
        *,
        name: str,
        kind: CollectionKind = CollectionKind.STATIC,
        parent_id: int | None = None,
        metadata: dict | None = None,
        smart_rule: dict | None = None,
    ) -> CollectionOperationResult:
        record = self.repository.create_collection(
            name=name,
            kind=kind,
            parent_id=parent_id,
            metadata=metadata,
            smart_rule=smart_rule,
        )
        return CollectionOperationResult(
            action=CollectionAction.CREATE,
            collection_id=record.collection_id,
            changed=True,
        )

    def rename_collection(self, collection_id: int, new_name: str) -> CollectionOperationResult:
        _ = self.repository.rename_collection(collection_id, new_name)
        return CollectionOperationResult(
            action=CollectionAction.RENAME,
            collection_id=collection_id,
            changed=True,
        )

    def delete_collection(self, collection_id: int) -> CollectionOperationResult:
        deleted = self.repository.delete_collection(collection_id)
        return CollectionOperationResult(
            action=CollectionAction.DELETE,
            collection_id=collection_id,
            changed=True,
            affected_image_ids=deleted,
        )

    def add_image(self, collection_id: int, image_id: int) -> CollectionOperationResult:
        changed = self.repository.add_image(collection_id, image_id)
        self._update_thumbnail(collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.ADD_IMAGE,
            collection_id=collection_id,
            changed=changed,
            affected_image_ids=[image_id] if changed else [],
        )

    def remove_image(self, collection_id: int, image_id: int) -> CollectionOperationResult:
        changed = self.repository.remove_image(collection_id, image_id)
        self._update_thumbnail(collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.REMOVE_IMAGE,
            collection_id=collection_id,
            changed=changed,
            affected_image_ids=[image_id] if changed else [],
        )

    def bulk_add_images(self, collection_id: int, image_ids: list[int]) -> CollectionOperationResult:
        changed = self.repository.bulk_add_images(collection_id, image_ids)
        self._update_thumbnail(collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.BULK_ADD,
            collection_id=collection_id,
            changed=len(changed) > 0,
            affected_image_ids=changed,
        )

    def bulk_remove_images(self, collection_id: int, image_ids: list[int]) -> CollectionOperationResult:
        changed = self.repository.bulk_remove_images(collection_id, image_ids)
        self._update_thumbnail(collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.BULK_REMOVE,
            collection_id=collection_id,
            changed=len(changed) > 0,
            affected_image_ids=changed,
        )

    def bulk_move_images(
        self,
        *,
        source_collection_id: int,
        target_collection_id: int,
        image_ids: list[int],
    ) -> CollectionOperationResult:
        moved = self.repository.bulk_move_images(source_collection_id, target_collection_id, image_ids)
        self._update_thumbnail(source_collection_id, repository=self.repository)
        self._update_thumbnail(target_collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.BULK_MOVE,
            collection_id=target_collection_id,
            changed=len(moved) > 0,
            affected_image_ids=moved,
        )

    def refresh_smart_collection(self, collection_id: int) -> CollectionOperationResult:
        changed = self.repository.refresh_smart_collection(collection_id)
        self._update_thumbnail(collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.REFRESH_SMART,
            collection_id=collection_id,
            changed=True,
            affected_image_ids=changed,
        )

    def update_collection_metadata(self, collection_id: int, metadata: dict) -> CollectionOperationResult:
        _ = self.repository.update_collection_metadata(collection_id, metadata)
        return CollectionOperationResult(
            action=CollectionAction.UPDATE_METADATA,
            collection_id=collection_id,
            changed=True,
        )

    def export_collection(self, collection_id: int) -> CollectionOperationResult:
        bundle = self.repository.export_collection(collection_id)
        return CollectionOperationResult(
            action=CollectionAction.EXPORT,
            collection_id=collection_id,
            changed=False,
            affected_image_ids=list(bundle.image_ids),
            details=self.builder.import_bundle_payload(bundle),
        )

    def import_collection(self, bundle: CollectionExportBundle, *, parent_id: int | None = None) -> CollectionOperationResult:
        imported = self.repository.import_collection(bundle, parent_id=parent_id)
        self._update_thumbnail(imported.collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.IMPORT,
            collection_id=imported.collection_id,
            changed=True,
            affected_image_ids=sorted(imported.image_ids),
        )

    def merge_collections(self, *, target_collection_id: int, source_collection_ids: list[int]) -> CollectionOperationResult:
        merged = self.repository.merge_collections(
            target_collection_id=target_collection_id,
            source_collection_ids=source_collection_ids,
        )
        self._update_thumbnail(target_collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.MERGE,
            collection_id=target_collection_id,
            changed=True,
            affected_image_ids=merged,
        )

    def split_collection(
        self,
        *,
        source_collection_id: int,
        groups: list[list[int]],
        names: list[str] | None = None,
    ) -> CollectionOperationResult:
        created = self.repository.split_collection(
            source_collection_id=source_collection_id,
            groups=groups,
            names=names,
        )
        for collection in created:
            self._update_thumbnail(collection.collection_id, repository=self.repository)
        self._update_thumbnail(source_collection_id, repository=self.repository)
        return CollectionOperationResult(
            action=CollectionAction.SPLIT,
            collection_id=source_collection_id,
            changed=len(created) > 0,
            affected_image_ids=[item.collection_id for item in created],
        )

    def detect_duplicates(self) -> CollectionOperationResult:
        duplicates = self.repository.detect_duplicates()
        flattened = [collection_id for group in duplicates for collection_id in group]
        return CollectionOperationResult(
            action=CollectionAction.DETECT_DUPLICATES,
            collection_id=-1,
            changed=len(duplicates) > 0,
            affected_image_ids=flattened,
            details={"groups": duplicates},
        )

    def search_collections(self, query: str) -> list[CollectionSearchResult]:
        return self.repository.search(query)

    def summary(self, collection_id: int) -> CollectionSummary | None:
        record = self.repository.get_collection(collection_id)
        if record is None:
            return None
        child_count = len(self.repository.list_children(collection_id))
        descendant_count = self.repository.descendant_count(collection_id)
        depth = self.repository.depth(collection_id)
        return self.builder.build_summary(
            record,
            child_count=child_count,
            descendant_count=descendant_count,
            depth=depth,
        )

    def hierarchy(self) -> list[CollectionHierarchyNode]:
        records = {item.collection_id: item for item in self.repository.list_collections()}

        def build_node(collection_id: int) -> CollectionHierarchyNode:
            record = records[collection_id]
            children_ids = [item.collection_id for item in records.values() if item.parent_id == collection_id]
            children = [build_node(child_id) for child_id in children_ids]
            return self.builder.build_hierarchy_node(record, children)

        roots = [item.collection_id for item in records.values() if item.parent_id is None]
        return [build_node(root_id) for root_id in roots]

    def process_job(
        self,
        payload: CollectionJobPayload,
        *,
        checkpoint: CollectionCheckpoint | None = None,
    ) -> CollectionOperationResult | None:
        action = payload.action

        # Use collection_id=-1 for create actions before id allocation.
        checkpoint_collection_id = payload.collection_id if payload.collection_id is not None else -1
        checkpoint_image_id = payload.image_id

        if checkpoint is not None and checkpoint.is_processed(action, checkpoint_collection_id, checkpoint_image_id):
            self.statistics.increment_processed()
            self.statistics.increment_skipped()
            self._emit(CollectionSkipped(action=action, collection_id=checkpoint_collection_id, reason="Already processed"))
            return None

        self.statistics.increment_processed()
        self._emit(CollectionStarted(action=action, collection_id=checkpoint_collection_id))

        try:
            repository = CollectionRepository()
            result = self._dispatch(payload, repository=repository)
            if checkpoint is not None:
                checkpoint.add_processed(action, checkpoint_collection_id, checkpoint_image_id)

            if result.changed:
                self.statistics.increment_changed()
            else:
                self.statistics.increment_skipped()

            self._emit(
                CollectionChanged(
                    action=result.action,
                    collection_id=result.collection_id,
                    changed=result.changed,
                    affected_count=len(result.affected_image_ids),
                )
            )
            return result
        except Exception as e:
            self.statistics.increment_failed()
            self._emit(CollectionFailed(action=action, collection_id=checkpoint_collection_id, error=str(e)))
            return None

    def process_jobs(
        self,
        payloads: Iterable[CollectionJobPayload],
        *,
        checkpoint: CollectionCheckpoint | None = None,
    ) -> list[CollectionOperationResult]:
        self.statistics = CollectionStatistics()
        self.statistics.start()
        results: list[CollectionOperationResult] = []
        payload_list = list(payloads)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.process_job, payload, checkpoint=checkpoint): payload for payload in payload_list}
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)

        self.statistics.finish()
        self._emit(
            CollectionCompleted(
                total=self.statistics.processed,
                changed=self.statistics.changed,
                skipped=self.statistics.skipped,
                failed=self.statistics.failed,
            )
        )
        return results

    def _dispatch(self, payload: CollectionJobPayload, *, repository: CollectionRepository) -> CollectionOperationResult:
        action = payload.action
        if action == CollectionAction.CREATE:
            name = payload.name or "Collection"
            record = repository.create_collection(
                name=name,
                kind=payload.kind,
                parent_id=payload.parent_id,
                metadata=payload.metadata,
                smart_rule=payload.smart_rule,
            )
            return CollectionOperationResult(action=CollectionAction.CREATE, collection_id=record.collection_id, changed=True)

        collection_id = payload.collection_id
        if collection_id is None and payload.name:
            record = repository.get_or_create_collection(name=payload.name, kind=payload.kind, parent_id=payload.parent_id)
            collection_id = record.collection_id

        if collection_id is None:
            raise ValueError("collection_id is required for this operation")

        if action == CollectionAction.RENAME:
            _ = repository.rename_collection(collection_id, payload.new_name or payload.name or "Collection")
            return CollectionOperationResult(action=CollectionAction.RENAME, collection_id=collection_id, changed=True)

        if action == CollectionAction.DELETE:
            deleted = repository.delete_collection(collection_id)
            return CollectionOperationResult(
                action=CollectionAction.DELETE,
                collection_id=collection_id,
                changed=True,
                affected_image_ids=deleted,
            )

        if action == CollectionAction.ADD_IMAGE:
            if payload.image_id is None:
                raise ValueError("image_id is required for add_image")
            changed = repository.add_image(collection_id, payload.image_id)
            self._update_thumbnail(collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.ADD_IMAGE,
                collection_id=collection_id,
                changed=changed,
                affected_image_ids=[payload.image_id] if changed else [],
            )

        if action == CollectionAction.REMOVE_IMAGE:
            if payload.image_id is None:
                raise ValueError("image_id is required for remove_image")
            changed = repository.remove_image(collection_id, payload.image_id)
            self._update_thumbnail(collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.REMOVE_IMAGE,
                collection_id=collection_id,
                changed=changed,
                affected_image_ids=[payload.image_id] if changed else [],
            )

        if action == CollectionAction.BULK_ADD:
            changed = repository.bulk_add_images(collection_id, payload.image_ids)
            self._update_thumbnail(collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.BULK_ADD,
                collection_id=collection_id,
                changed=len(changed) > 0,
                affected_image_ids=changed,
            )

        if action == CollectionAction.BULK_REMOVE:
            changed = repository.bulk_remove_images(collection_id, payload.image_ids)
            self._update_thumbnail(collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.BULK_REMOVE,
                collection_id=collection_id,
                changed=len(changed) > 0,
                affected_image_ids=changed,
            )

        if action == CollectionAction.BULK_MOVE:
            if payload.source_collection_id is None or payload.target_collection_id is None:
                raise ValueError("source_collection_id and target_collection_id are required for bulk_move")
            moved = repository.bulk_move_images(
                source_collection_id=payload.source_collection_id,
                target_collection_id=payload.target_collection_id,
                image_ids=payload.image_ids,
            )
            self._update_thumbnail(payload.source_collection_id, repository=repository)
            self._update_thumbnail(payload.target_collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.BULK_MOVE,
                collection_id=payload.target_collection_id,
                changed=len(moved) > 0,
                affected_image_ids=moved,
            )

        if action == CollectionAction.REFRESH_SMART:
            changed = repository.refresh_smart_collection(collection_id)
            self._update_thumbnail(collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.REFRESH_SMART,
                collection_id=collection_id,
                changed=True,
                affected_image_ids=changed,
            )

        if action == CollectionAction.UPDATE_METADATA:
            _ = repository.update_collection_metadata(collection_id, payload.metadata)
            return CollectionOperationResult(
                action=CollectionAction.UPDATE_METADATA,
                collection_id=collection_id,
                changed=True,
            )

        if action == CollectionAction.EXPORT:
            bundle = repository.export_collection(collection_id)
            return CollectionOperationResult(
                action=CollectionAction.EXPORT,
                collection_id=collection_id,
                changed=False,
                affected_image_ids=list(bundle.image_ids),
                details=self.builder.import_bundle_payload(bundle),
            )

        if action == CollectionAction.IMPORT:
            import_bundle = payload.import_bundle or {}
            name = str(import_bundle.get("name", payload.name or "Imported Collection"))
            raw_kind = str(import_bundle.get("kind", payload.kind.value)).strip().lower()
            kind = CollectionKind.SMART if raw_kind == CollectionKind.SMART.value else CollectionKind.STATIC
            image_ids = [
                int(item)
                for item in import_bundle.get("image_ids", [])
                if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
            ]
            bundle = CollectionExportBundle(
                collection_id=int(import_bundle.get("collection_id", 0) or 0),
                name=name,
                kind=kind,
                parent_id=payload.parent_id,
                image_ids=image_ids,
                metadata=import_bundle.get("metadata", {}) if isinstance(import_bundle.get("metadata"), dict) else {},
                smart_rule=import_bundle.get("smart_rule", {}) if isinstance(import_bundle.get("smart_rule"), dict) else {},
            )
            imported = repository.import_collection(bundle, parent_id=payload.parent_id)
            self._update_thumbnail(imported.collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.IMPORT,
                collection_id=imported.collection_id,
                changed=True,
                affected_image_ids=sorted(imported.image_ids),
            )

        if action == CollectionAction.MERGE:
            source_ids = payload.source_collection_ids
            if not source_ids and payload.source_collection_id is not None:
                source_ids = [payload.source_collection_id]
            merged = repository.merge_collections(target_collection_id=collection_id, source_collection_ids=source_ids)
            self._update_thumbnail(collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.MERGE,
                collection_id=collection_id,
                changed=True,
                affected_image_ids=merged,
            )

        if action == CollectionAction.SPLIT:
            created = repository.split_collection(
                source_collection_id=collection_id,
                groups=payload.split_groups,
                names=payload.split_names,
            )
            for item in created:
                self._update_thumbnail(item.collection_id, repository=repository)
            self._update_thumbnail(collection_id, repository=repository)
            return CollectionOperationResult(
                action=CollectionAction.SPLIT,
                collection_id=collection_id,
                changed=len(created) > 0,
                affected_image_ids=[item.collection_id for item in created],
            )

        if action == CollectionAction.DETECT_DUPLICATES:
            duplicates = repository.detect_duplicates()
            flattened = [identifier for group in duplicates for identifier in group]
            return CollectionOperationResult(
                action=CollectionAction.DETECT_DUPLICATES,
                collection_id=-1,
                changed=len(duplicates) > 0,
                affected_image_ids=flattened,
                details={"groups": duplicates},
            )

        if action == CollectionAction.SEARCH:
            query = payload.search_query or payload.name or ""
            matches = repository.search(query)
            return CollectionOperationResult(
                action=CollectionAction.SEARCH,
                collection_id=-1,
                changed=False,
                details={
                    "query": query,
                    "results": [
                        {
                            "collection_id": item.collection_id,
                            "name": item.name,
                            "score": item.score,
                            "reason": item.reason,
                        }
                        for item in matches
                    ],
                },
            )

        raise ValueError(f"Unsupported collection action: {action.value}")

    def _update_thumbnail(self, collection_id: int, *, repository: CollectionRepository) -> None:
        record = repository.get_collection(collection_id)
        if record is None:
            return

        paths: list[str] = []
        for image_id in sorted(record.image_ids):
            path = repository.get_image_path(image_id)
            if path:
                paths.append(path)

        thumbnail = self.builder.choose_thumbnail_path(paths)
        repository.set_thumbnail(collection_id, thumbnail)

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
