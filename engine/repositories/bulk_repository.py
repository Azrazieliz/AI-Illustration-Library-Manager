from __future__ import annotations

import copy
from datetime import datetime, timezone
from threading import Lock

from engine.bulk.bulk_models import BulkBatch, BulkFailure, BulkItem, BulkRollbackRecord, BulkRequest


class BulkRepository:
    """In-memory store for bulk batch state and rollback metadata."""

    _batches: dict[str, BulkBatch] = {}
    _rollback_records: dict[str, list[BulkRollbackRecord]] = {}
    _lock = Lock()

    @classmethod
    def reset_state(cls) -> None:
        with cls._lock:
            cls._batches = {}
            cls._rollback_records = {}

    def save_batch(self, batch: BulkBatch) -> BulkBatch:
        with self._lock:
            batch.updated_at = datetime.now(timezone.utc)
            self._batches[batch.batch_id] = batch
            self._rollback_records.setdefault(batch.batch_id, batch.rollback_records)
            return batch

    def get_batch(self, batch_id: str) -> BulkBatch | None:
        with self._lock:
            return self._batches.get(batch_id)

    def list_batches(self) -> list[BulkBatch]:
        with self._lock:
            return list(self._batches.values())

    def create_batch(self, request: BulkRequest, items: list[BulkItem]) -> BulkBatch:
        batch = BulkBatch(request=request, items=items)
        return self.save_batch(batch)

    def append_failure(self, batch_id: str, failure: BulkFailure) -> None:
        with self._lock:
            batch = self._batches[batch_id]
            if failure not in batch.failures:
                batch.failures.append(failure)
            batch.updated_at = datetime.now(timezone.utc)
            self._batches[batch_id] = batch

    def append_rollback_record(self, batch_id: str, record: BulkRollbackRecord) -> None:
        with self._lock:
            batch = self._batches[batch_id]
            batch.rollback_records.append(record)
            batch.updated_at = datetime.now(timezone.utc)
            self._rollback_records.setdefault(batch_id, []).append(record)
            self._batches[batch_id] = batch

    def list_rollback_records(self, batch_id: str | None = None) -> list[BulkRollbackRecord]:
        with self._lock:
            if batch_id is None:
                records: list[BulkRollbackRecord] = []
                for record_list in self._rollback_records.values():
                    records.extend(record_list)
                return records
            return list(self._rollback_records.get(batch_id, []))

    def request_cancel(self, batch_id: str) -> BulkBatch:
        with self._lock:
            batch = self._batches[batch_id]
            batch.cancel_requested = True
            batch.updated_at = datetime.now(timezone.utc)
            self._batches[batch_id] = batch
            return batch

    def update_batch(self, batch: BulkBatch) -> BulkBatch:
        with self._lock:
            batch.updated_at = datetime.now(timezone.utc)
            self._batches[batch.batch_id] = batch
            return batch

    def clone_batch(self, batch_id: str) -> BulkBatch | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            return copy.deepcopy(batch) if batch is not None else None
