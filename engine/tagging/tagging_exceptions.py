from __future__ import annotations


class TaggingException(Exception):
    """Base exception for automatic tagging subsystem errors."""


class TaggingBackendError(TaggingException):
    """Raised when a tagging backend fails."""


class TaggingBuildError(TaggingException):
    """Raised when tag generation cannot be completed."""


class TaggingPersistenceError(TaggingException):
    """Raised when generated tags cannot be persisted."""
