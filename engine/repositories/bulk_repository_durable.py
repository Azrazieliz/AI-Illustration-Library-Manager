from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

from sqlalchemy import delete, select, update

from engine.bulk.bulk_models import (
    BulkBatch,
    BulkBatchStatus,
    BulkFailure,
    BulkItem,
    BulkItemStatus,
    BulkOperationType,
    BulkRequest,
    BulkRollbackRecord,
)
from engine.database.models.bulk_state import BulkStateRecord
from engine.database.session import session_scope
from engine.organizer.organizer_models import OrganizationRule
from engine.rename.rename_models import RenameRule
from engine.repositories.bulk_repository import InMemoryBulkRepository


class DurableBulkRepository(InMemoryBulkRepository):
    """Versioned state for resumable bulk batches and filesystem rollback metadata."""

    _state_key = "default"
    _state_lock = RLock()

    def __init__(self) -> None:
        super().__init__()
        self._lock = self._state_lock
        self._batches: dict[str, BulkBatch] = {}
        self._rollback_records: dict[str, list[BulkRollbackRecord]] = {}
        self._state_version: int | None = None
        self._load_state()

    @classmethod
    def reset_state(cls) -> None:
        with cls._state_lock:
            InMemoryBulkRepository.reset_state()
            with session_scope() as session:
                session.execute(delete(BulkStateRecord))

    def save_batch(self, batch: BulkBatch) -> BulkBatch:
        with self._lock:
            result = super().save_batch(batch)
            self._persist_state()
            return result

    def append_failure(self, batch_id: str, failure: BulkFailure) -> None:
        with self._lock:
            super().append_failure(batch_id, failure)
            self._persist_state()

    def append_rollback_record(self, batch_id: str, record: BulkRollbackRecord) -> None:
        with self._lock:
            super().append_rollback_record(batch_id, record)
            self._persist_state()

    def request_cancel(self, batch_id: str) -> BulkBatch:
        with self._lock:
            result = super().request_cancel(batch_id)
            self._persist_state()
            return result

    def update_batch(self, batch: BulkBatch) -> BulkBatch:
        with self._lock:
            result = super().update_batch(batch)
            self._persist_state()
            return result

    def get_batch(self, batch_id: str) -> BulkBatch | None:
        with self._lock:
            return super().get_batch(batch_id)

    def list_batches(self) -> list[BulkBatch]:
        with self._lock:
            return super().list_batches()

    def list_rollback_records(self, batch_id: str | None = None) -> list[BulkRollbackRecord]:
        with self._lock:
            return super().list_rollback_records(batch_id)

    def clone_batch(self, batch_id: str) -> BulkBatch | None:
        with self._lock:
            return super().clone_batch(batch_id)

    def _load_state(self) -> None:
        with self._lock, session_scope() as session:
            row = session.scalar(select(BulkStateRecord).where(BulkStateRecord.state_key == self._state_key))
            if row is None:
                return
            self._state_version = row.version
            self._restore_state(dict(row.state_payload or {}))

    def _persist_state(self) -> None:
        payload = self._state_payload()
        with session_scope() as session:
            row = session.scalar(select(BulkStateRecord).where(BulkStateRecord.state_key == self._state_key))
            if row is None:
                if self._state_version is not None:
                    raise RuntimeError("Bulk state was removed while this repository was active")
                row = BulkStateRecord(state_key=self._state_key, state_payload=payload)
                session.add(row)
                session.flush()
                self._state_version = row.version
                return
            if self._state_version is None or row.version != self._state_version:
                raise RuntimeError("Bulk state changed in another repository instance; reload before writing")
            result = session.execute(
                update(BulkStateRecord)
                .where(BulkStateRecord.id == row.id, BulkStateRecord.version == self._state_version)
                .values(
                    state_payload=payload,
                    version=BulkStateRecord.version + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if int(result.rowcount or 0) != 1:
                raise RuntimeError("Bulk state changed concurrently; retry the operation")
            self._state_version += 1

    def _state_payload(self) -> dict[str, Any]:
        return {"batches": [self._batch_to_payload(batch) for batch in self._batches.values()]}

    def _restore_state(self, payload: dict[str, Any]) -> None:
        self._batches = {}
        self._rollback_records = {}
        for item in payload.get("batches", []):
            if not isinstance(item, dict):
                continue
            batch = self._batch_from_payload(item)
            self._batches[batch.batch_id] = batch
            self._rollback_records[batch.batch_id] = batch.rollback_records

    @classmethod
    def _batch_to_payload(cls, batch: BulkBatch) -> dict[str, Any]:
        return {
            "batch_id": batch.batch_id,
            "request": None if batch.request is None else cls._request_to_payload(batch.request),
            "items": [
                {
                    "entity_id": item.entity_id,
                    "operation_type": item.operation_type.value,
                    "source_path": cls._path_value(item.source_path),
                    "target_path": cls._path_value(item.target_path),
                    "status": item.status.value,
                    "reason": item.reason,
                    "metadata": cls._json_value(item.metadata),
                    "batch_index": item.batch_index,
                }
                for item in batch.items
            ],
            "failures": [
                {
                    "entity_id": failure.entity_id,
                    "operation_type": failure.operation_type.value,
                    "error": failure.error,
                    "source_path": cls._path_value(failure.source_path),
                    "target_path": cls._path_value(failure.target_path),
                    "batch_index": failure.batch_index,
                }
                for failure in batch.failures
            ],
            "rollback_records": [
                {
                    "batch_id": record.batch_id,
                    "entity_id": record.entity_id,
                    "operation_type": record.operation_type.value,
                    "source_path": cls._path_value(record.source_path),
                    "target_path": cls._path_value(record.target_path),
                    "previous_value": cls._json_value(record.previous_value),
                    "restored_value": cls._json_value(record.restored_value),
                    "created_at": record.created_at.isoformat(),
                    "metadata": cls._json_value(record.metadata),
                }
                for record in batch.rollback_records
            ],
            "status": batch.status.value,
            "next_index": batch.next_index,
            "cancel_requested": batch.cancel_requested,
            "created_at": batch.created_at.isoformat(),
            "updated_at": batch.updated_at.isoformat(),
        }

    @classmethod
    def _batch_from_payload(cls, payload: dict[str, Any]) -> BulkBatch:
        request_payload = payload.get("request")
        batch = BulkBatch(
            batch_id=str(payload.get("batch_id", "")),
            request=cls._request_from_payload(request_payload) if isinstance(request_payload, dict) else None,
            items=[
                BulkItem(
                    entity_id=int(item.get("entity_id", 0)),
                    operation_type=BulkOperationType(str(item.get("operation_type", BulkOperationType.DELETE.value))),
                    source_path=cls._path_from_value(item.get("source_path")),
                    target_path=cls._path_from_value(item.get("target_path")),
                    status=BulkItemStatus(str(item.get("status", BulkItemStatus.PENDING.value))),
                    reason=item.get("reason"),
                    metadata=dict(item.get("metadata", {})),
                    batch_index=int(item.get("batch_index", 0)),
                )
                for item in payload.get("items", [])
                if isinstance(item, dict)
            ],
            failures=[
                BulkFailure(
                    entity_id=int(item.get("entity_id", 0)),
                    operation_type=BulkOperationType(str(item.get("operation_type", BulkOperationType.DELETE.value))),
                    error=str(item.get("error", "")),
                    source_path=cls._path_from_value(item.get("source_path")),
                    target_path=cls._path_from_value(item.get("target_path")),
                    batch_index=int(item.get("batch_index", 0)),
                )
                for item in payload.get("failures", [])
                if isinstance(item, dict)
            ],
            rollback_records=[
                BulkRollbackRecord(
                    batch_id=str(item.get("batch_id", payload.get("batch_id", ""))),
                    entity_id=int(item.get("entity_id", 0)),
                    operation_type=BulkOperationType(str(item.get("operation_type", BulkOperationType.DELETE.value))),
                    source_path=cls._path_from_value(item.get("source_path")),
                    target_path=cls._path_from_value(item.get("target_path")),
                    previous_value=item.get("previous_value"),
                    restored_value=item.get("restored_value"),
                    created_at=cls._as_utc(item.get("created_at")),
                    metadata=dict(item.get("metadata", {})),
                )
                for item in payload.get("rollback_records", [])
                if isinstance(item, dict)
            ],
            status=BulkBatchStatus(str(payload.get("status", BulkBatchStatus.PENDING.value))),
            next_index=int(payload.get("next_index", 0)),
            cancel_requested=bool(payload.get("cancel_requested", False)),
            created_at=cls._as_utc(payload.get("created_at")),
            updated_at=cls._as_utc(payload.get("updated_at")),
        )
        return batch

    @classmethod
    def _request_to_payload(cls, request: BulkRequest) -> dict[str, Any]:
        return {
            "operation_type": request.operation_type.value,
            "image_ids": list(request.image_ids),
            "review_ids": list(request.review_ids),
            "target_directory": cls._path_value(request.target_directory),
            "target_path": cls._path_value(request.target_path),
            "tag_name": request.tag_name,
            "tag_category": request.tag_category,
            "collection_id": request.collection_id,
            "reviewer": request.reviewer,
            "reason": request.reason,
            "rename_rule": cls._rename_rule_to_payload(request.rename_rule),
            "organizer_rules": [cls._organizer_rule_to_payload(rule) for rule in request.organizer_rules or []],
            "metadata": cls._json_value(request.metadata),
        }

    @classmethod
    def _request_from_payload(cls, payload: dict[str, Any]) -> BulkRequest:
        rename_rule = payload.get("rename_rule")
        organizer_rules = payload.get("organizer_rules", [])
        return BulkRequest(
            operation_type=BulkOperationType(str(payload.get("operation_type", BulkOperationType.DELETE.value))),
            image_ids=[int(value) for value in payload.get("image_ids", [])],
            review_ids=[int(value) for value in payload.get("review_ids", [])],
            target_directory=cls._path_from_value(payload.get("target_directory")),
            target_path=cls._path_from_value(payload.get("target_path")),
            tag_name=payload.get("tag_name"),
            tag_category=payload.get("tag_category"),
            collection_id=payload.get("collection_id"),
            reviewer=payload.get("reviewer"),
            reason=payload.get("reason"),
            rename_rule=cls._rename_rule_from_payload(rename_rule) if isinstance(rename_rule, dict) else None,
            organizer_rules=[
                cls._organizer_rule_from_payload(rule)
                for rule in organizer_rules
                if isinstance(rule, dict)
            ] or None,
            metadata=dict(payload.get("metadata", {})),
        )

    @staticmethod
    def _rename_rule_to_payload(rule: RenameRule | None) -> dict[str, Any] | None:
        if rule is None:
            return None
        return {
            "template": rule.template,
            "unknown_defaults": dict(rule.unknown_defaults),
            "numbering_width": rule.numbering_width,
            "max_stem_length": rule.max_stem_length,
        }

    @staticmethod
    def _rename_rule_from_payload(payload: dict[str, Any]) -> RenameRule:
        return RenameRule(
            template=str(payload.get("template", RenameRule().template)),
            unknown_defaults={str(key): str(value) for key, value in dict(payload.get("unknown_defaults", {})).items()},
            numbering_width=int(payload.get("numbering_width", 3)),
            max_stem_length=int(payload.get("max_stem_length", 220)),
        )

    @staticmethod
    def _organizer_rule_to_payload(rule: OrganizationRule) -> dict[str, Any]:
        return {
            "name": rule.name,
            "directory_template": rule.directory_template,
            "priority": rule.priority,
            "is_fallback": rule.is_fallback,
            "required_fields": list(rule.required_fields),
        }

    @staticmethod
    def _organizer_rule_from_payload(payload: dict[str, Any]) -> OrganizationRule:
        return OrganizationRule(
            name=str(payload.get("name", "")),
            directory_template=str(payload.get("directory_template", "")),
            priority=int(payload.get("priority", 100)),
            is_fallback=bool(payload.get("is_fallback", False)),
            required_fields=tuple(str(value) for value in payload.get("required_fields", [])),
        )

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, datetime):
            return cls._as_utc(value).isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {str(key): cls._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        raise ValueError(f"Bulk state values must be JSON-compatible, got {type(value).__name__}")

    @staticmethod
    def _path_value(value: Path | None) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _path_from_value(value: Any) -> Path | None:
        return None if value in {None, ""} else Path(str(value))

    @staticmethod
    def _as_utc(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                return datetime.now(timezone.utc)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)