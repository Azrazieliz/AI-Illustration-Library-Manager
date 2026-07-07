from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from engine.database.models.review import Review as ReviewRecord
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
    """Repository for review persistence operations and queue state."""

    _queue_reviews: dict[int, ReviewItem] = {}
    _queue_batches: dict[str, ReviewBatch] = {}
    _queue_history: dict[int, list[ReviewDecision]] = {}
    _next_queue_review_id: int = 1
    _lock = Lock()

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(ReviewRecord, session=session)

    @classmethod
    def reset_state(cls) -> None:
        with cls._lock:
            cls._queue_reviews = {}
            cls._queue_batches = {}
            cls._queue_history = {}
            cls._next_queue_review_id = 1

    # Legacy DB-backed review methods remain for compatibility.
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

    # Queue foundation methods.
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
        normalized_path = Path(source_path)
        signature = self._signature(
            image_id=image_id,
            source_path=normalized_path,
            operation_type=operation_type,
            proposed_value=proposed_value,
            current_value=current_value,
            series=series,
            character=character,
        )

        with self._lock:
            duplicate = self._find_pending_duplicate(signature)
            if duplicate is not None:
                raise ValueError(f"Duplicate pending review item: {duplicate.review_id}")

            review_id = self._next_queue_review_id
            self._next_queue_review_id += 1
            item = ReviewItem(
                review_id=review_id,
                image_id=image_id,
                source_path=normalized_path,
                operation_type=operation_type,
                confidence=confidence,
                proposed_value=copy.deepcopy(proposed_value),
                current_value=copy.deepcopy(current_value),
                reviewer=reviewer,
                decision_reason=decision_reason,
                series=series,
                character=character,
                batch_id=batch_id,
            )
            self._queue_reviews[review_id] = item
            self._queue_history.setdefault(review_id, [])
            return item

    def get_review_item(self, review_id: int) -> ReviewItem | None:
        with self._lock:
            item = self._queue_reviews.get(review_id)
            if item is None:
                return None
            return copy.deepcopy(item)

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
        with self._lock:
            for item in self._queue_reviews.values():
                item_signature = self._signature(
                    image_id=item.image_id,
                    source_path=item.source_path,
                    operation_type=item.operation_type,
                    proposed_value=item.proposed_value,
                    current_value=item.current_value,
                    series=item.series,
                    character=item.character,
                )
                if item_signature == signature:
                    return copy.deepcopy(item)
        return None

    def list_review_items(self) -> list[ReviewItem]:
        with self._lock:
            return [copy.deepcopy(item) for item in self._queue_reviews.values()]

    def search_review_items(self, query: str) -> list[ReviewItem]:
        needle = query.strip().lower()
        if not needle:
            return self.list_review_items()

        results = [
            item
            for item in self.list_review_items()
            if needle in self._search_text(item)
        ]
        return results

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
            items = [item for item in items if item.timestamp >= date_from]
        if date_to is not None:
            items = [item for item in items if item.timestamp <= date_to]
        if series is not None:
            items = [item for item in items if (item.series or "") == series]
        if character is not None:
            items = [item for item in items if (item.character or "") == character]
        return items

    def sort_review_items(self, items: list[ReviewItem], *, sort_by: str = "timestamp", descending: bool = True) -> list[ReviewItem]:
        key_map = {
            "timestamp": lambda item: item.timestamp,
            "confidence": lambda item: item.confidence,
            "status": lambda item: item.status.value,
            "operation_type": lambda item: item.operation_type,
            "series": lambda item: item.series or "",
            "character": lambda item: item.character or "",
            "image_id": lambda item: item.image_id,
        }
        key_func = key_map.get(sort_by, key_map["timestamp"])
        return sorted(items, key=key_func, reverse=descending)

    def paginate_review_items(self, items: list[ReviewItem], *, page: int, page_size: int) -> ReviewSearchResult:
        page = max(1, page)
        page_size = max(1, page_size)
        start = (page - 1) * page_size
        end = start + page_size
        return ReviewSearchResult(items=items[start:end], total=len(items), page=page, page_size=page_size)

    def create_review_batch(self, items: list[ReviewItem]) -> ReviewBatch:
        batch_id = str(uuid4())
        batch_items = [copy.deepcopy(item) for item in items]
        with self._lock:
            for item in self._queue_reviews.values():
                if item.review_id in {batch_item.review_id for batch_item in batch_items}:
                    item.batch_id = batch_id
            batch = ReviewBatch(batch_id=batch_id, items=batch_items)
            self._queue_batches[batch_id] = batch
            return copy.deepcopy(batch)

    def apply_review_decision(
        self,
        review_id: int,
        *,
        decision: ReviewDecisionType,
        reviewer: str | None = None,
        reason: str | None = None,
        batch_id: str | None = None,
    ) -> ReviewDecision:
        with self._lock:
            item = self._queue_reviews.get(review_id)
            if item is None:
                raise ValueError(f"Review item not found: {review_id}")
            if item.status is not ReviewStatus.PENDING:
                raise ValueError(f"Review item is not pending: {review_id}")

            previous_status = item.status
            previous_value = copy.deepcopy(item.current_value)

            if decision is ReviewDecisionType.APPROVE:
                new_status = ReviewStatus.APPROVED
                new_value = copy.deepcopy(item.proposed_value)
                item.current_value = copy.deepcopy(item.proposed_value)
            elif decision is ReviewDecisionType.REJECT:
                new_status = ReviewStatus.REJECTED
                new_value = copy.deepcopy(item.current_value)
            else:
                new_status = ReviewStatus.SKIPPED
                new_value = copy.deepcopy(item.current_value)

            item.status = new_status
            item.reviewer = reviewer
            item.decision_reason = reason
            item.batch_id = batch_id or item.batch_id

            decision_record = ReviewDecision(
                review_id=review_id,
                decision=decision,
                previous_status=previous_status,
                new_status=new_status,
                previous_value=previous_value,
                new_value=copy.deepcopy(new_value),
                reviewer=reviewer,
                reason=reason,
                batch_id=batch_id or item.batch_id,
            )
            self._queue_history.setdefault(review_id, []).append(decision_record)

            batch = self._queue_batches.get(batch_id or "")
            if batch is not None:
                batch.decisions.append(copy.deepcopy(decision_record))

            return copy.deepcopy(decision_record)

    def rollback_review_batch(self, batch_id: str) -> ReviewResult:
        with self._lock:
            batch = self._queue_batches.get(batch_id)
            if batch is None:
                raise ValueError(f"Review batch not found: {batch_id}")

            reverted_items: list[ReviewItem] = []
            reverted_decisions: list[ReviewDecision] = []
            for decision in reversed(batch.decisions):
                item = self._queue_reviews.get(decision.review_id)
                if item is None:
                    continue
                item.status = decision.previous_status
                item.current_value = copy.deepcopy(decision.previous_value)
                item.reviewer = None
                item.decision_reason = None
                item.batch_id = None
                reverted_items.append(copy.deepcopy(item))
                reverted_decisions.append(copy.deepcopy(decision))

            return ReviewResult(
                batch_id=batch_id,
                items=reverted_items,
                decisions=reverted_decisions,
                dry_run=False,
                applied=False,
                rolled_back=True,
            )

    def get_decision_history(self, review_id: int) -> list[ReviewDecision]:
        with self._lock:
            return [copy.deepcopy(item) for item in self._queue_history.get(review_id, [])]

    def _find_pending_duplicate(self, signature: str) -> ReviewItem | None:
        for item in self._queue_reviews.values():
            if item.status is ReviewStatus.PENDING and self._signature(
                image_id=item.image_id,
                source_path=item.source_path,
                operation_type=item.operation_type,
                proposed_value=item.proposed_value,
                current_value=item.current_value,
                series=item.series,
                character=item.character,
            ) == signature:
                return item
        return None

    @staticmethod
    def _signature(
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
            "proposed_value": ReviewRepository._normalize_value(proposed_value),
            "current_value": ReviewRepository._normalize_value(current_value),
            "series": series or "",
            "character": character or "",
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {key: ReviewRepository._normalize_value(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            return [ReviewRepository._normalize_value(item) for item in value]
        return value

    @staticmethod
    def _search_text(item: ReviewItem) -> str:
        payload = [
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
        return " ".join(payload).lower()
