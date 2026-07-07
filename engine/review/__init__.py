from __future__ import annotations

from engine.review.review_exceptions import (
    ReviewCreationError,
    ReviewDecisionError,
    ReviewException,
    ReviewRollbackError,
)
from engine.review.review_models import (
    ReviewBatch,
    ReviewCheckpoint,
    ReviewDecision,
    ReviewDecisionType,
    ReviewItem,
    ReviewResult,
    ReviewSearchResult,
    ReviewStatus,
)
from engine.review.review_statistics import ReviewStatistics

__all__ = [
    "ReviewBatch",
    "ReviewCheckpoint",
    "ReviewCreationError",
    "ReviewDecision",
    "ReviewDecisionError",
    "ReviewDecisionType",
    "ReviewException",
    "ReviewItem",
    "ReviewResult",
    "ReviewRollbackError",
    "ReviewSearchResult",
    "ReviewStatistics",
    "ReviewStatus",
    "ReviewEngine",
    "ReviewService",
    "ReviewWorker",
]


def __getattr__(name: str):
    if name == "ReviewEngine":
        from engine.review.review_engine import ReviewEngine

        return ReviewEngine
    if name == "ReviewService":
        from engine.review.review_service import ReviewService

        return ReviewService
    if name == "ReviewWorker":
        from engine.review.review_worker import ReviewWorker

        return ReviewWorker
    raise AttributeError(name)
