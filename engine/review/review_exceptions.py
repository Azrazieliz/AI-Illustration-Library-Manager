from __future__ import annotations


class ReviewException(Exception):
    """Base exception for review queue errors."""

    pass


class ReviewCreationError(ReviewException):
    """Raised when a review item cannot be created."""

    pass


class ReviewDecisionError(ReviewException):
    """Raised when a review decision cannot be applied."""

    pass


class ReviewRollbackError(ReviewException):
    """Raised when review batch rollback fails."""

    pass
