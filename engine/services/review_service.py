from __future__ import annotations

from engine.database.models.review import Review
from engine.services.base_service import BaseService


class ReviewService(BaseService[Review]):
    """Service layer for review entries."""

    def create_review(self, *, image_id: int, status: str = "pending") -> Review:
        review = Review(image_id=image_id, status=status)
        self.add(review)
        self.commit()
        return review

    def approve_review(self, review: Review) -> Review:
        review.status = "approved"
        self.commit()
        return review

    def reject_review(self, review: Review) -> Review:
        review.status = "rejected"
        self.commit()
        return review

    def list_pending(self) -> list[Review]:
        return list(self.session.query(Review).filter(Review.status == "pending").all())
