from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from engine.collections.collection_builder import CollectionBuilder
from engine.collections.collection_exceptions import CollectionNotFoundError, CollectionValidationError
from engine.collections.collection_models import CollectionExportBundle, CollectionKind, CollectionRecord, CollectionSearchResult
from engine.database.models.collection import CollectionMembershipRecord, CollectionRecordRow
from engine.database.models.image import Image
from engine.database.session import session_scope
from engine.dataset.dataset_builder import DatasetBuilder
from engine.repositories.base_repository import BaseRepository
from engine.repositories.dataset_repository import DatasetRepository


class DurableCollectionRepository(BaseRepository[Image]):
    """Transactional repository for durable collection hierarchy and memberships."""

    _lock = RLock()

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(Image, session=session)
        self.builder = CollectionBuilder()

    @classmethod
    def reset_state(cls) -> None:
        with cls._lock, session_scope() as session:
            session.execute(delete(CollectionMembershipRecord))
            session.execute(delete(CollectionRecordRow))

    def create_collection(
        self,
        *,
        name: str,
        kind: CollectionKind,
        parent_id: int | None = None,
        metadata: dict | None = None,
        smart_rule: dict | None = None,
    ) -> CollectionRecord:
        with self._lock, session_scope() as session:
            if parent_id is not None and session.get(CollectionRecordRow, parent_id) is None:
                raise CollectionNotFoundError(f"Parent collection not found: {parent_id}")
            row = CollectionRecordRow(
                name=name,
                kind=kind.value,
                parent_id=parent_id,
                metadata_payload=dict(metadata or {}),
                smart_rule=dict(smart_rule or {}),
            )
            session.add(row)
            session.flush()
            return self._to_record(session, row)

    def get_collection(self, collection_id: int) -> CollectionRecord | None:
        with self._lock, session_scope() as session:
            row = session.get(CollectionRecordRow, collection_id)
            return None if row is None else self._to_record(session, row)

    def get_collection_by_name(self, name: str, *, parent_id: int | None = None) -> CollectionRecord | None:
        target = name.strip().lower()
        with self._lock, session_scope() as session:
            statement = select(CollectionRecordRow).order_by(CollectionRecordRow.id)
            if parent_id is None:
                statement = statement.where(CollectionRecordRow.parent_id.is_(None))
            else:
                statement = statement.where(CollectionRecordRow.parent_id == parent_id)
            for row in session.scalars(statement):
                if row.name.strip().lower() == target:
                    return self._to_record(session, row)
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
        with self._lock, session_scope() as session:
            rows = list(session.scalars(select(CollectionRecordRow).order_by(CollectionRecordRow.id)))
            return self._to_records(session, rows)

    def list_children(self, parent_id: int | None) -> list[CollectionRecord]:
        with self._lock, session_scope() as session:
            statement = select(CollectionRecordRow).order_by(CollectionRecordRow.id)
            if parent_id is None:
                statement = statement.where(CollectionRecordRow.parent_id.is_(None))
            else:
                statement = statement.where(CollectionRecordRow.parent_id == parent_id)
            return self._to_records(session, list(session.scalars(statement)))

    def rename_collection(self, collection_id: int, new_name: str) -> CollectionRecord:
        with self._lock, session_scope() as session:
            row = self._require_row(session, collection_id)
            row.name = new_name
            row.updated_at = datetime.now(timezone.utc)
            session.flush()
            return self._to_record(session, row)

    def update_collection_metadata(self, collection_id: int, metadata: dict) -> CollectionRecord:
        with self._lock, session_scope() as session:
            row = self._require_row(session, collection_id)
            row.metadata_payload = dict(metadata)
            row.updated_at = datetime.now(timezone.utc)
            session.flush()
            return self._to_record(session, row)

    def delete_collection(self, collection_id: int) -> list[int]:
        with self._lock, session_scope() as session:
            rows = list(session.scalars(select(CollectionRecordRow)))
            by_id = {row.id: row for row in rows}
            if collection_id not in by_id:
                raise CollectionNotFoundError(f"Collection not found: {collection_id}")
            identifiers = set(self._collect_descendants(rows, collection_id))
            identifiers.add(collection_id)
            session.execute(delete(CollectionMembershipRecord).where(CollectionMembershipRecord.collection_id.in_(identifiers)))
            for identifier in sorted(identifiers, reverse=True):
                session.delete(by_id[identifier])
            return sorted(identifiers, reverse=True)

    def set_parent(self, collection_id: int, parent_id: int | None) -> CollectionRecord:
        with self._lock, session_scope() as session:
            row = self._require_row(session, collection_id)
            if parent_id is not None and session.get(CollectionRecordRow, parent_id) is None:
                raise CollectionNotFoundError(f"Parent collection not found: {parent_id}")
            if parent_id == collection_id:
                raise CollectionValidationError("Collection cannot be parent of itself")
            row.parent_id = parent_id
            row.updated_at = datetime.now(timezone.utc)
            session.flush()
            return self._to_record(session, row)

    def clear_parent(self, collection_id: int) -> CollectionRecord:
        return self.set_parent(collection_id, None)

    def add_image(self, collection_id: int, image_id: int) -> bool:
        with self._lock, session_scope() as session:
            row = self._require_row(session, collection_id)
            existing = session.scalar(
                select(CollectionMembershipRecord.id).where(
                    CollectionMembershipRecord.collection_id == collection_id,
                    CollectionMembershipRecord.image_id == image_id,
                )
            )
            if existing is not None:
                return False
            session.add(CollectionMembershipRecord(collection_id=collection_id, image_id=image_id))
            row.updated_at = datetime.now(timezone.utc)
            return True

    def remove_image(self, collection_id: int, image_id: int) -> bool:
        with self._lock, session_scope() as session:
            row = self._require_row(session, collection_id)
            membership = session.scalar(
                select(CollectionMembershipRecord).where(
                    CollectionMembershipRecord.collection_id == collection_id,
                    CollectionMembershipRecord.image_id == image_id,
                )
            )
            if membership is None:
                return False
            session.delete(membership)
            row.updated_at = datetime.now(timezone.utc)
            return True

    def bulk_add_images(self, collection_id: int, image_ids: list[int]) -> list[int]:
        return [image_id for image_id in image_ids if self.add_image(collection_id, image_id)]

    def bulk_remove_images(self, collection_id: int, image_ids: list[int]) -> list[int]:
        return [image_id for image_id in image_ids if self.remove_image(collection_id, image_id)]

    def bulk_move_images(self, source_collection_id: int, target_collection_id: int, image_ids: list[int]) -> list[int]:
        moved: list[int] = []
        for image_id in image_ids:
            if not self.remove_image(source_collection_id, image_id):
                continue
            _ = self.add_image(target_collection_id, image_id)
            moved.append(image_id)
        return moved

    def set_thumbnail(self, collection_id: int, thumbnail_path: str | None) -> CollectionRecord:
        with self._lock, session_scope() as session:
            row = self._require_row(session, collection_id)
            row.thumbnail_path = thumbnail_path
            row.updated_at = datetime.now(timezone.utc)
            session.flush()
            return self._to_record(session, row)

    def get_image_path(self, image_id: int) -> str | None:
        with self._lock, session_scope() as session:
            image = session.get(Image, image_id)
            return None if image is None else image.original_path

    def refresh_smart_collection(self, collection_id: int) -> list[int]:
        collection = self.get_collection(collection_id)
        if collection is None:
            raise CollectionNotFoundError(f"Collection not found: {collection_id}")
        if collection.kind != CollectionKind.SMART:
            raise CollectionValidationError("refresh_smart_collection is only valid for smart collections")

        dataset_builder = DatasetBuilder(DatasetRepository())
        matched: list[int] = []
        with self._lock, session_scope() as session:
            images = list(session.scalars(select(Image)))
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
            if self.builder.matches_smart_rule(payload, collection.smart_rule):
                matched.append(image.id)

        self._replace_image_ids(collection_id, set(matched))
        return matched

    def descendant_count(self, collection_id: int) -> int:
        records = self.list_collections()
        if collection_id not in {record.collection_id for record in records}:
            return 0
        return len(set(self._collect_descendants(records, collection_id)))

    def depth(self, collection_id: int) -> int:
        records = {record.collection_id: record for record in self.list_collections()}
        current = records.get(collection_id)
        if current is None:
            return 0
        depth = 0
        visited = {collection_id}
        while current.parent_id is not None:
            parent_id = current.parent_id
            if parent_id in visited:
                break
            parent = records.get(parent_id)
            if parent is None:
                break
            visited.add(parent_id)
            depth += 1
            current = parent
        return depth

    def export_collection(self, collection_id: int) -> CollectionExportBundle:
        collection = self.get_collection(collection_id)
        if collection is None:
            raise CollectionNotFoundError(f"Collection not found: {collection_id}")
        return self.builder.build_export_bundle(collection)

    def import_collection(
        self,
        bundle: CollectionExportBundle,
        *,
        parent_id: int | None = None,
        rename_conflicts: bool = True,
    ) -> CollectionRecord:
        name = bundle.name
        if rename_conflicts:
            suffix = 1
            while self.get_collection_by_name(name, parent_id=parent_id) is not None:
                suffix += 1
                name = f"{bundle.name} ({suffix})"

        created = self.create_collection(
            name=name,
            kind=bundle.kind,
            parent_id=parent_id if parent_id is not None else bundle.parent_id,
            metadata=bundle.metadata,
            smart_rule=bundle.smart_rule,
        )
        _ = self.bulk_add_images(created.collection_id, list(bundle.image_ids))
        return self.get_collection(created.collection_id) or created

    def merge_collections(self, *, target_collection_id: int, source_collection_ids: list[int]) -> list[int]:
        target = self.get_collection(target_collection_id)
        if target is None:
            raise CollectionNotFoundError(f"Collection not found: {target_collection_id}")

        merged_images = set(target.image_ids)
        for source_id in source_collection_ids:
            if source_id == target_collection_id:
                continue
            source = self.get_collection(source_id)
            if source is None:
                continue
            merged_images.update(source.image_ids)
            self.delete_collection(source_id)

        self._replace_image_ids(target_collection_id, merged_images)
        return sorted(merged_images)

    def split_collection(
        self,
        *,
        source_collection_id: int,
        groups: list[list[int]],
        names: list[str] | None = None,
    ) -> list[CollectionRecord]:
        source = self.get_collection(source_collection_id)
        if source is None:
            raise CollectionNotFoundError(f"Collection not found: {source_collection_id}")

        created: list[CollectionRecord] = []
        all_grouped: set[int] = set()
        names = names or []
        for index, image_group in enumerate(groups):
            if not image_group:
                continue
            group_name = names[index] if index < len(names) else f"{source.name} Split {index + 1}"
            child = self.create_collection(
                name=group_name,
                kind=source.kind,
                parent_id=source_collection_id,
                metadata=dict(source.metadata),
                smart_rule=dict(source.smart_rule),
            )
            valid_ids = [image_id for image_id in image_group if image_id in source.image_ids]
            _ = self.bulk_add_images(child.collection_id, valid_ids)
            all_grouped.update(valid_ids)
            created.append(self.get_collection(child.collection_id) or child)

        self._replace_image_ids(source_collection_id, source.image_ids.difference(all_grouped))
        return created

    def detect_duplicates(self) -> list[list[int]]:
        by_signature: dict[str, list[int]] = {}
        for collection in self.list_collections():
            by_signature.setdefault(self._signature(collection), []).append(collection.collection_id)
        return [identifiers for identifiers in by_signature.values() if len(identifiers) > 1]

    def search(self, query: str) -> list[CollectionSearchResult]:
        term = query.strip().lower()
        if not term:
            return []

        out: list[CollectionSearchResult] = []
        for collection in self.list_collections():
            score = 0.0
            reason = ""
            if term in collection.name.lower():
                score += 1.0
                reason = "name"
            for key, value in collection.metadata.items():
                if term in str(key).lower() or term in str(value).lower():
                    score += 0.6
                    reason = "metadata"
                    break
            if collection.kind == CollectionKind.SMART:
                for key, value in collection.smart_rule.items():
                    if term in str(key).lower() or term in str(value).lower():
                        score += 0.4
                        reason = "smart_rule"
                        break
            if score > 0.0:
                out.append(
                    CollectionSearchResult(
                        collection_id=collection.collection_id,
                        name=collection.name,
                        score=score,
                        reason=reason or "match",
                    )
                )
        out.sort(key=lambda item: (item.score, item.collection_id), reverse=True)
        return out

    def _replace_image_ids(self, collection_id: int, image_ids: set[int]) -> None:
        with self._lock, session_scope() as session:
            row = self._require_row(session, collection_id)
            session.execute(delete(CollectionMembershipRecord).where(CollectionMembershipRecord.collection_id == collection_id))
            session.add_all(
                CollectionMembershipRecord(collection_id=collection_id, image_id=image_id)
                for image_id in sorted(image_ids)
            )
            row.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _require_row(session: Session, collection_id: int) -> CollectionRecordRow:
        row = session.get(CollectionRecordRow, collection_id)
        if row is None:
            raise CollectionNotFoundError(f"Collection not found: {collection_id}")
        return row

    @staticmethod
    def _collect_descendants(records: list[Any], collection_id: int) -> list[int]:
        descendants: list[int] = []
        queue = [collection_id]
        while queue:
            current = queue.pop(0)
            children: list[int] = []
            for item in records:
                if item.parent_id != current:
                    continue
                identifier = getattr(item, "collection_id", None)
                children.append(item.id if identifier is None else identifier)
            descendants.extend(children)
            queue.extend(children)
        return descendants

    @classmethod
    def _to_records(cls, session: Session, rows: list[CollectionRecordRow]) -> list[CollectionRecord]:
        memberships: dict[int, set[int]] = {row.id: set() for row in rows}
        identifiers = list(memberships)
        if identifiers:
            for collection_id, image_id in session.execute(
                select(CollectionMembershipRecord.collection_id, CollectionMembershipRecord.image_id).where(
                    CollectionMembershipRecord.collection_id.in_(identifiers)
                )
            ):
                memberships.setdefault(collection_id, set()).add(image_id)
        return [cls._to_record(session, row, image_ids=memberships.get(row.id, set())) for row in rows]

    @classmethod
    def _to_record(
        cls,
        session: Session,
        row: CollectionRecordRow,
        *,
        image_ids: set[int] | None = None,
    ) -> CollectionRecord:
        if image_ids is None:
            image_ids = set(
                session.scalars(
                    select(CollectionMembershipRecord.image_id).where(CollectionMembershipRecord.collection_id == row.id)
                )
            )
        return CollectionRecord(
            collection_id=row.id,
            name=row.name,
            kind=CollectionKind(row.kind),
            parent_id=row.parent_id,
            image_ids=set(image_ids),
            metadata=dict(row.metadata_payload or {}),
            smart_rule=dict(row.smart_rule or {}),
            thumbnail_path=row.thumbnail_path,
            created_at=cls._as_utc(row.created_at),
            updated_at=cls._as_utc(row.updated_at),
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _signature(collection: CollectionRecord) -> str:
        image_signature = ",".join(str(item) for item in sorted(collection.image_ids))
        metadata_signature = "|".join(
            f"{key}:{collection.metadata[key]}" for key in sorted(collection.metadata.keys())
        )
        return f"{collection.kind.value}:{collection.name.strip().lower()}:{image_signature}:{metadata_signature}"