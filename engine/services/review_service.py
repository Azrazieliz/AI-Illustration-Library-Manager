from __future__ import annotations

from engine.database.models.review import Review
from engine.repositories.review_repository import ReviewRepository
from engine.services.base_service import BaseService


class ReviewService(BaseService[Review]):
    """Service layer for review entries."""

    def __init__(self, repository: ReviewRepository | None = None) -> None:
        super().__init__(repository or ReviewRepository())
        self.repository = repository or ReviewRepository()

    def create_review(self, *, image_id: int, status: str = "pending") -> Review:
        return self.repository.create_review(image_id=image_id, status=status)

    def approve_review(self, review: Review) -> Review:
        return self.repository.approve_review(review)

    def reject_review(self, review: Review) -> Review:
        return self.repository.reject_review(review)

    def list_pending(self) -> list[Review]:
        return self.repository.list_pending()
