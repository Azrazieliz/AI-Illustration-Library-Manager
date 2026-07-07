from __future__ import annotations


class CollectionException(Exception):
    """Base exception for collection management failures."""


class CollectionNotFoundError(CollectionException):
    """Raised when a collection cannot be found."""


class CollectionValidationError(CollectionException):
    """Raised when invalid collection operations are requested."""


class CollectionPersistenceError(CollectionException):
    """Raised when collection data cannot be persisted."""
