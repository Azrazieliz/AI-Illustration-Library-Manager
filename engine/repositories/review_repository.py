from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from engine.database.models.review import Review as ReviewRecord
from engine.database.models.review_queue import ReviewBatchRecord, ReviewDecisionRecord, ReviewQueueItemRecord
from engine.database.session import session_scope
from engine.review.review_models import (
    ReviewBatch,
    ReviewDecision,
    ReviewDecisionType,
    ReviewItem,
    ReviewResult,
    ReviewSearchResult,
    ReviewStatus,
)
from engine.repositories.base_repository import BaseRepository


class ReviewRepository(BaseRepository[ReviewRecord]):
    """Repository for legacy reviews and durable manual-review queue state."""

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(ReviewRecord, session=session)

    @classmethod
    def reset_state(cls) -> None:
        with session_scope() as session:
            session.execute(delete(ReviewDecisionRecord))
            session.execute(delete(ReviewBatchRecord))
            session.execute(delete(ReviewQueueItemRecord))

    def create_review(self, *, image_id: int, status: str = "pending") -> ReviewRecord:
        review = ReviewRecord(image_id=image_id, status=status)
        self.add(review)
        self.commit()
        return review

    def approve_review(self, review: ReviewRecord) -> ReviewRecord:
        review.status = "approved"
        self.commit()
        return review

    def reject_review(self, review: ReviewRecord) -> ReviewRecord:
        review.status = "rejected"
        self.commit()
        return review

    def list_pending(self) -> list[ReviewRecord]:
        return list(self.session.query(ReviewRecord).filter(ReviewRecord.status == "pending").all())

    def create_review_item(
        self,
        *,
        image_id: int,
        source_path: Path,
        operation_type: str,
        confidence: float,
        proposed_value: Any,
        current_value: Any,
        reviewer: str | None = None,
        decision_reason: str | None = None,
        series: str | None = None,
        character: str | None = None,
        batch_id: str | None = None,
    ) -> ReviewItem:
        signature = self._signature(
            image_id=image_id,
            source_path=source_path,
            operation_type=operation_type,
            proposed_value=proposed_value,
            current_value=current_value,
            series=series,
            character=character,
        )
        with session_scope() as session:
            duplicate = session.scalar(
                select(ReviewQueueItemRecord)
                .where(
                    ReviewQueueItemRecord.signature == signature,
                    ReviewQueueItemRecord.status == ReviewStatus.PENDING.value,
                )
                .limit(1)
            )
            if duplicate is not None:
                raise ValueError(f"Duplicate pending review item: {duplicate.id}")
            row = ReviewQueueItemRecord(
                item_uuid=str(uuid4()),
                image_id=image_id,
                source_path=str(Path(source_path)),
                operation_type=operation_type,
                confidence=float(confidence),
                proposed_value=self._json_value(proposed_value),
                current_value=self._json_value(current_value),
                timestamp=datetime.now(timezone.utc),
                status=ReviewStatus.PENDING.value,
                reviewer=reviewer,
                decision_reason=decision_reason,
                series=series,
                character=character,
                batch_id=batch_id,
                signature=signature,
            )
            session.add(row)
            session.flush()
            return self._to_item(row)

    def get_review_item(self, review_id: int) -> ReviewItem | None:
        with session_scope() as session:
            row = session.get(ReviewQueueItemRecord, review_id)
            return None if row is None else self._to_item(row)

    def get_review_item_by_signature(
        self,
        *,
        image_id: int,
        source_path: Path,
        operation_type: str,
        proposed_value: Any,
        current_value: Any,
        series: str | None,
        character: str | None,
    ) -> ReviewItem | None:
        signature = self._signature(
            image_id=image_id,
            source_path=source_path,
            operation_type=operation_type,
            proposed_value=proposed_value,
            current_value=current_value,
            series=series,
            character=character,
        )
        with session_scope() as session:
            row = session.scalar(select(ReviewQueueItemRecord).where(ReviewQueueItemRecord.signature == signature).limit(1))
            return None if row is None else self._to_item(row)

    def list_review_items(self) -> list[ReviewItem]:
        with session_scope() as session:
            rows = list(session.scalars(select(ReviewQueueItemRecord).order_by(ReviewQueueItemRecord.id)))
            return [self._to_item(row) for row in rows]

    def search_review_items(self, query: str) -> list[ReviewItem]:
        needle = query.strip().lower()
        items = self.list_review_items()
        return items if not needle else [item for item in items if needle in self._search_text(item)]

    def filter_review_items(
        self,
        *,
        operation_type: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
        status: ReviewStatus | str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        series: str | None = None,
        character: str | None = None,
    ) -> list[ReviewItem]:
        items = self.list_review_items()
        if operation_type is not None:
            items = [item for item in items if item.operation_type == operation_type]
        if min_confidence is not None:
            items = [item for item in items if item.confidence >= min_confidence]
        if max_confidence is not None:
            items = [item for item in items if item.confidence <= max_confidence]
        if status is not None:
            status_value = status.value if isinstance(status, ReviewStatus) else str(status)
            items = [item for item in items if item.status.value == status_value]
        if date_from is not None:
            items = [item for item in items if item.timestamp >= self._as_utc(date_from)]
        if date_to is not None:
            items = [item for item in items if item.timestamp <= self._as_utc(date_to)]
        if series is not None:
            items = [item for item in items if (item.series or "") == series]
        if character is not None:
            items = [item for item in items if (item.character or "") == character]
        return items

    @staticmethod
    def sort_review_items(items: list[ReviewItem], *, sort_by: str = "timestamp", descending: bool = True) -> list[ReviewItem]:
        key_map = {
            "timestamp": lambda item: item.timestamp,
            "confidence": lambda item: item.confidence,
            "status": lambda item: item.status.value,
            "operation_type": lambda item: item.operation_type,
            "series": lambda item: item.series or "",
            "character": lambda item: item.character or "",
            "image_id": lambda item: item.image_id,
        }
        return sorted(items, key=key_map.get(sort_by, key_map["timestamp"]), reverse=descending)

    @staticmethod
    def paginate_review_items(items: list[ReviewItem], *, page: int, page_size: int) -> ReviewSearchResult:
        page = max(1, page)
        page_size = max(1, page_size)
        start = (page - 1) * page_size
        return ReviewSearchResult(items=items[start : start + page_size], total=len(items), page=page, page_size=page_size)

    def create_review_batch(self, items: list[ReviewItem]) -> ReviewBatch:
        requested_ids = [item.review_id for item in items]
        batch_id = str(uuid4())
        with session_scope() as session:
            rows = list(session.scalars(select(ReviewQueueItemRecord).where(ReviewQueueItemRecord.id.in_(requested_ids)))) if requested_ids else []
            rows_by_id = {row.id: row for row in rows}
            review_ids = [item_id for item_id in requested_ids if item_id in rows_by_id]
            for row in rows:
                row.batch_id = batch_id
            batch = ReviewBatchRecord(batch_id=batch_id, review_ids=review_ids)
            session.add(batch)
            session.flush()
            return self._to_batch(session, batch)

    def latest_active_batch(self) -> ReviewBatch | None:
        with session_scope() as session:
            batch = session.scalar(
                select(ReviewBatchRecord)
                .where(ReviewBatchRecord.state == "active")
                .order_by(ReviewBatchRecord.created_at.desc(), ReviewBatchRecord.id.desc())
                .limit(1)
            )
            return None if batch is None else self._to_batch(session, batch)

    def apply_review_decision(
        self,
        review_id: int,
        *,
        decision: ReviewDecisionType,
        reviewer: str | None = None,
        reason: str | None = None,
        batch_id: str | None = None,
    ) -> ReviewDecision:
        with session_scope() as session:
            row = session.get(ReviewQueueItemRecord, review_id)
            if row is None:
                raise ValueError(f"Review item not found: {review_id}")
            if row.status != ReviewStatus.PENDING.value:
                raise ValueError(f"Review item is not pending: {review_id}")
            previous_status = ReviewStatus(row.status)
            previous_value = self._json_value(row.current_value)
            effective_batch_id = batch_id or row.batch_id
            if decision is ReviewDecisionType.APPROVE:
                new_status = ReviewStatus.APPROVED
                new_value = self._json_value(row.proposed_value)
                row.current_value = new_value
            elif decision is ReviewDecisionType.REJECT:
                new_status = ReviewStatus.REJECTED
                new_value = previous_value
            else:
                new_status = ReviewStatus.SKIPPED
                new_value = previous_value
            row.status = new_status.value
            row.reviewer = reviewer
            row.decision_reason = reason
            row.batch_id = effective_batch_id
            record = ReviewDecision(
                review_id=review_id,
                decision=decision,
                previous_status=previous_status,
                new_status=new_status,
                previous_value=previous_value,
                new_value=new_value,
                reviewer=reviewer,
                reason=reason,
                batch_id=effective_batch_id,
            )
            session.add(
                ReviewDecisionRecord(
                    review_id=record.review_id,
                    decision=record.decision.value,
                    previous_status=record.previous_status.value,
                    new_status=record.new_status.value,
                    previous_value=self._json_value(record.previous_value),
                    new_value=self._json_value(record.new_value),
                    reviewer=record.reviewer,
                    reason=record.reason,
                    decided_at=record.decided_at,
                    batch_id=record.batch_id,
                )
            )
            return record

    def rollback_review_batch(self, batch_id: str) -> ReviewResult:
        with session_scope() as session:
            batch = session.scalar(select(ReviewBatchRecord).where(ReviewBatchRecord.batch_id == batch_id))
            if batch is None:
                raise ValueError(f"Review batch not found: {batch_id}")
            if batch.state != "active":
                raise ValueError(f"Review batch is no longer active: {batch_id}")
            records = list(
                session.scalars(
                    select(ReviewDecisionRecord)
                    .where(ReviewDecisionRecord.batch_id == batch_id)
                    .order_by(ReviewDecisionRecord.id.desc())
                )
            )
            items: list[ReviewItem] = []
            decisions: list[ReviewDecision] = []
            for record in records:
                row = session.get(ReviewQueueItemRecord, record.review_id)
                if row is None:
                    continue
                row.status = record.previous_status
                row.current_value = self._json_value(record.previous_value)
                row.reviewer = None
                row.decision_reason = None
                row.batch_id = None
                items.append(self._to_item(row))
                decisions.append(self._to_decision(record))
            batch.state = "rolled_back"
            return ReviewResult(
                batch_id=batch_id,
                items=items,
                decisions=decisions,
                dry_run=False,
                applied=False,
                rolled_back=True,
            )

    def restore_review_item(
        self,
        review_id: int,
        *,
        status: ReviewStatus | str,
        current_value: Any,
    ) -> ReviewItem | None:
        """Restore a review item from externally managed rollback metadata."""
        status_value = status.value if isinstance(status, ReviewStatus) else str(status)
        try:
            restored_status = ReviewStatus(status_value)
        except ValueError:
            restored_status = ReviewStatus.PENDING
        with session_scope() as session:
            row = session.get(ReviewQueueItemRecord, review_id)
            if row is None:
                return None
            row.status = restored_status.value
            row.current_value = self._json_value(current_value)
            row.reviewer = None
            row.decision_reason = None
            row.batch_id = None
            return self._to_item(row)

    def get_decision_history(self, review_id: int) -> list[ReviewDecision]:
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(ReviewDecisionRecord)
                    .where(ReviewDecisionRecord.review_id == review_id)
                    .order_by(ReviewDecisionRecord.id)
                )
            )
            return [self._to_decision(row) for row in rows]

    def delete_review_items(self, review_ids: list[int]) -> int:
        identifiers = sorted({int(review_id) for review_id in review_ids})
        if not identifiers:
            return 0
        with session_scope() as session:
            session.execute(delete(ReviewDecisionRecord).where(ReviewDecisionRecord.review_id.in_(identifiers)))
            result = session.execute(delete(ReviewQueueItemRecord).where(ReviewQueueItemRecord.id.in_(identifiers)))
            return int(result.rowcount or 0)

    @classmethod
    def _to_item(cls, row: ReviewQueueItemRecord) -> ReviewItem:
        return ReviewItem(
            review_id=row.id,
            item_uuid=row.item_uuid,
            image_id=row.image_id,
            source_path=Path(row.source_path),
            operation_type=row.operation_type,
            confidence=row.confidence,
            proposed_value=cls._json_value(row.proposed_value),
            current_value=cls._json_value(row.current_value),
            timestamp=cls._as_utc(row.timestamp),
            status=ReviewStatus(row.status),
            reviewer=row.reviewer,
            decision_reason=row.decision_reason,
            series=row.series,
            character=row.character,
            batch_id=row.batch_id,
        )

    @classmethod
    def _to_batch(cls, session: Session, row: ReviewBatchRecord) -> ReviewBatch:
        review_ids = [int(value) for value in row.review_ids]
        rows_by_id = {
            item.id: item
            for item in session.scalars(select(ReviewQueueItemRecord).where(ReviewQueueItemRecord.id.in_(review_ids)))
        } if review_ids else {}
        decisions = list(
            session.scalars(
                select(ReviewDecisionRecord)
                .where(ReviewDecisionRecord.batch_id == row.batch_id)
                .order_by(ReviewDecisionRecord.id)
            )
        )
        return ReviewBatch(
            batch_id=row.batch_id,
            items=[cls._to_item(rows_by_id[item_id]) for item_id in review_ids if item_id in rows_by_id],
            decisions=[cls._to_decision(record) for record in decisions],
            created_at=cls._as_utc(row.created_at),
        )

    @classmethod
    def _to_decision(cls, row: ReviewDecisionRecord) -> ReviewDecision:
        return ReviewDecision(
            review_id=row.review_id,
            decision=ReviewDecisionType(row.decision),
            previous_status=ReviewStatus(row.previous_status),
            new_status=ReviewStatus(row.new_status),
            previous_value=cls._json_value(row.previous_value),
            new_value=cls._json_value(row.new_value),
            reviewer=row.reviewer,
            reason=row.reason,
            decided_at=cls._as_utc(row.decided_at),
            batch_id=row.batch_id,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @classmethod
    def _signature(
        cls,
        *,
        image_id: int,
        source_path: Path,
        operation_type: str,
        proposed_value: Any,
        current_value: Any,
        series: str | None,
        character: str | None,
    ) -> str:
        payload = {
            "image_id": image_id,
            "source_path": str(Path(source_path).resolve()),
            "operation_type": operation_type,
            "proposed_value": cls._json_value(proposed_value),
            "current_value": cls._json_value(current_value),
            "series": series or "",
            "character": character or "",
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, datetime):
            return cls._as_utc(value).isoformat()
        if isinstance(value, dict):
            return {str(key): cls._json_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        raise ValueError(f"Review values must be JSON-compatible, got {type(value).__name__}")

    _normalize_value = _json_value

    @staticmethod
    def _search_text(item: ReviewItem) -> str:
        return " ".join(
            [
                str(item.review_id),
                str(item.image_id),
                str(item.source_path),
                item.operation_type,
                str(item.confidence),
                str(item.proposed_value),
                str(item.current_value),
                item.status.value,
                item.reviewer or "",
                item.decision_reason or "",
                item.series or "",
                item.character or "",
            ]
        ).lower()