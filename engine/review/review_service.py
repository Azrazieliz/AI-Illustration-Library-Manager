from __future__ import annotations

from pathlib import Path

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.review.review_engine import ReviewEngine
from engine.review.review_models import ReviewBatch, ReviewItem, ReviewResult, ReviewSearchResult, ReviewStatus


class ReviewService:
    """Service facade connecting the review engine to pipeline jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: ReviewEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or ReviewEngine(callback=self._handle_event)

    def create_review_item(self, **kwargs) -> ReviewItem:
        return self.engine.create_review_item(**kwargs)

    def approve_review(self, review_id: int, *, reviewer: str | None = None, reason: str | None = None):
        return self.engine.approve_review(review_id, reviewer=reviewer, reason=reason)

    def reject_review(self, review_id: int, *, reviewer: str | None = None, reason: str | None = None):
        return self.engine.reject_review(review_id, reviewer=reviewer, reason=reason)

    def skip_review(self, review_id: int, *, reviewer: str | None = None, reason: str | None = None):
        return self.engine.skip_review(review_id, reviewer=reviewer, reason=reason)

    def bulk_approve(self, review_ids: list[int], *, reviewer: str | None = None, reason: str | None = None, dry_run: bool = False):
        return self.engine.bulk_approve(review_ids, reviewer=reviewer, reason=reason, dry_run=dry_run)

    def bulk_reject(self, review_ids: list[int], *, reviewer: str | None = None, reason: str | None = None, dry_run: bool = False):
        return self.engine.bulk_reject(review_ids, reviewer=reviewer, reason=reason, dry_run=dry_run)

    def search_reviews(self, query: str):
        return self.engine.search_reviews(query)

    def filter_reviews(self, **kwargs):
        return self.engine.filter_reviews(**kwargs)

    def sort_reviews(self, items, *, sort_by: str = "timestamp", descending: bool = True):
        return self.engine.sort_reviews(items, sort_by=sort_by, descending=descending)

    def paginate_reviews(self, items, *, page: int, page_size: int) -> ReviewSearchResult:
        return self.engine.paginate_reviews(items, page=page, page_size=page_size)

    def create_batch(self, review_ids: list[int]) -> ReviewBatch:
        return self.engine.create_batch(review_ids)

    def rollback_last_batch(self) -> ReviewResult | None:
        return self.engine.rollback_last_batch()

    def process_review_job(self, job: PipelineJob) -> ReviewItem | None:
        if not job.source_path:
            return None
        if (job.metadata or {}).get("stage") not in {None, "review"}:
            return None
        return self.engine.process_review_job(job)

    def process_review_jobs(self, jobs: list[PipelineJob]) -> list[ReviewItem]:
        results: list[ReviewItem] = []
        for job in jobs:
            result = self.process_review_job(job)
            if result is not None:
                results.append(result)
        return results

    def _handle_event(self, event: object) -> None:
        return None
