from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from engine.logging import get_logger
from engine.pipeline import PipelineJob
from engine.review.review_exceptions import ReviewCreationError, ReviewDecisionError, ReviewRollbackError
from engine.review.review_models import (
    ReviewBatch,
    ReviewDecision,
    ReviewDecisionType,
    ReviewItem,
    ReviewResult,
    ReviewSearchResult,
    ReviewStatus,
)
from engine.review.review_statistics import ReviewStatistics
from engine.repositories.review_repository import ReviewRepository


class ReviewEngine:
    """Creates and manages review queue items for manual validation."""

    def __init__(
        self,
        *,
        repository: ReviewRepository | None = None,
        callback: Callable[[object], None] | None = None,
    ) -> None:
        self.repository = repository or ReviewRepository()
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = ReviewStatistics()
        self._last_batch: ReviewBatch | None = None

    def create_review_item(
        self,
        *,
        image_id: int,
        source_path: Path | str,
        operation_type: str,
        confidence: float,
        proposed_value,
        current_value,
        reviewer: str | None = None,
        decision_reason: str | None = None,
        series: str | None = None,
        character: str | None = None,
        batch_id: str | None = None,
    ) -> ReviewItem:
        try:
            item = self.repository.create_review_item(
                image_id=image_id,
                source_path=Path(source_path),
                operation_type=operation_type,
                confidence=confidence,
                proposed_value=proposed_value,
                current_value=current_value,
                reviewer=reviewer,
                decision_reason=decision_reason,
                series=series,
                character=character,
                batch_id=batch_id,
            )
        except ValueError as exc:
            self.statistics.increment_duplicate_reviews_prevented()
            existing = self.repository.get_review_item_by_signature(
                image_id=image_id,
                source_path=Path(source_path),
                operation_type=operation_type,
                proposed_value=proposed_value,
                current_value=current_value,
                series=series,
                character=character,
            )
            if existing is not None:
                return existing
            raise ReviewCreationError(str(exc)) from exc

        self.statistics.increment_total()
        self.statistics.increment_pending()
        self.statistics.record_confidence(item.confidence)
        return item

    def approve_review(
        self,
        review_id: int,
        *,
        reviewer: str | None = None,
        reason: str | None = None,
    ) -> ReviewDecision:
        return self._apply_decision(review_id, ReviewDecisionType.APPROVE, reviewer=reviewer, reason=reason)

    def reject_review(
        self,
        review_id: int,
        *,
        reviewer: str | None = None,
        reason: str | None = None,
    ) -> ReviewDecision:
        return self._apply_decision(review_id, ReviewDecisionType.REJECT, reviewer=reviewer, reason=reason)

    def skip_review(
        self,
        review_id: int,
        *,
        reviewer: str | None = None,
        reason: str | None = None,
    ) -> ReviewDecision:
        return self._apply_decision(review_id, ReviewDecisionType.SKIP, reviewer=reviewer, reason=reason)

    def bulk_approve(
        self,
        review_ids: Iterable[int],
        *,
        reviewer: str | None = None,
        reason: str | None = None,
        dry_run: bool = False,
    ) -> ReviewResult:
        return self._bulk_decide(review_ids, ReviewDecisionType.APPROVE, reviewer=reviewer, reason=reason, dry_run=dry_run)

    def bulk_reject(
        self,
        review_ids: Iterable[int],
        *,
        reviewer: str | None = None,
        reason: str | None = None,
        dry_run: bool = False,
    ) -> ReviewResult:
        return self._bulk_decide(review_ids, ReviewDecisionType.REJECT, reviewer=reviewer, reason=reason, dry_run=dry_run)

    def search_reviews(self, query: str) -> list[ReviewItem]:
        return self.repository.search_review_items(query)

    def filter_reviews(
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
        return self.repository.filter_review_items(
            operation_type=operation_type,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            status=status,
            date_from=date_from,
            date_to=date_to,
            series=series,
            character=character,
        )

    def sort_reviews(
        self,
        items: Iterable[ReviewItem],
        *,
        sort_by: str = "timestamp",
        descending: bool = True,
    ) -> list[ReviewItem]:
        return self.repository.sort_review_items(list(items), sort_by=sort_by, descending=descending)

    def paginate_reviews(self, items: Iterable[ReviewItem], *, page: int, page_size: int) -> ReviewSearchResult:
        return self.repository.paginate_review_items(list(items), page=page, page_size=page_size)

    def create_batch(self, review_ids: Iterable[int]) -> ReviewBatch:
        items = [self.repository.get_review_item(review_id) for review_id in review_ids]
        resolved_items = [item for item in items if item is not None]
        batch = self.repository.create_review_batch(resolved_items)
        self._last_batch = batch
        self.statistics.increment_batches_created()
        return batch

    def rollback_last_batch(self) -> ReviewResult | None:
        if self._last_batch is None:
            return None
        try:
            result = self.repository.rollback_review_batch(self._last_batch.batch_id)
        except ValueError as exc:
            self.statistics.increment_failed()
            raise ReviewRollbackError(str(exc)) from exc

        for decision in result.decisions:
            if decision.new_status is ReviewStatus.APPROVED:
                self.statistics.decrement_approved()
            elif decision.new_status is ReviewStatus.REJECTED:
                self.statistics.decrement_rejected()
            else:
                self.statistics.decrement_skipped()
            self.statistics.increment_pending()
        self.statistics.increment_batches_rolled_back()
        self._last_batch = None
        return result

    def process_review_job(self, job: PipelineJob) -> ReviewItem | None:
        if not job.source_path:
            return None

        metadata = job.metadata or {}
        operation_type = str(metadata.get("operation_type") or metadata.get("stage") or "unknown")
        confidence = float(metadata.get("confidence", 0.0))
        item = self.create_review_item(
            image_id=int(metadata.get("image_id", 0)),
            source_path=Path(job.source_path),
            operation_type=operation_type,
            confidence=confidence,
            proposed_value=metadata.get("proposed_value"),
            current_value=metadata.get("current_value"),
            reviewer=metadata.get("reviewer"),
            decision_reason=metadata.get("decision_reason"),
            series=metadata.get("series"),
            character=metadata.get("character"),
            batch_id=metadata.get("batch_id"),
        )
        self._emit(item)
        return item

    def _bulk_decide(
        self,
        review_ids: Iterable[int],
        decision: ReviewDecisionType,
        *,
        reviewer: str | None,
        reason: str | None,
        dry_run: bool,
    ) -> ReviewResult:
        batch_id = str(uuid4())
        items = []
        decisions = []
        skipped = 0
        failed = 0
        pending_items = []
        for review_id in review_ids:
            item = self.repository.get_review_item(review_id)
            if item is None:
                skipped += 1
                continue
            items.append(item)
            pending_items.append(item)
            if dry_run:
                continue
        if not dry_run and pending_items:
            batch = self.repository.create_review_batch(pending_items)
            batch_id = batch.batch_id
            for item in pending_items:
                try:
                    decisions.append(
                        self._apply_decision(item.review_id, decision, reviewer=reviewer, reason=reason, batch_id=batch_id)
                    )
                except ReviewDecisionError:
                    failed += 1
        if not dry_run:
            self._last_batch = ReviewBatch(batch_id=batch_id, items=items, decisions=decisions)
        return ReviewResult(
            batch_id=batch_id,
            items=items,
            decisions=decisions,
            dry_run=dry_run,
            applied=not dry_run,
            skipped=skipped,
            failed=failed,
        )

    def _apply_decision(
        self,
        review_id: int,
        decision: ReviewDecisionType,
        *,
        reviewer: str | None,
        reason: str | None,
        batch_id: str | None = None,
    ) -> ReviewDecision:
        try:
            decision_record = self.repository.apply_review_decision(
                review_id,
                decision=decision,
                reviewer=reviewer,
                reason=reason,
                batch_id=batch_id,
            )
        except ValueError as exc:
            self.statistics.increment_failed()
            raise ReviewDecisionError(str(exc)) from exc

        if decision == ReviewDecisionType.APPROVE:
            self.statistics.decrement_pending()
            self.statistics.increment_approved()
        elif decision == ReviewDecisionType.REJECT:
            self.statistics.decrement_pending()
            self.statistics.increment_rejected()
        else:
            self.statistics.decrement_pending()
            self.statistics.increment_skipped()
        return decision_record

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
