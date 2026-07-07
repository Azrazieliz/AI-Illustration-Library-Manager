from __future__ import annotations


class BulkException(Exception):
    """Base exception for bulk operation errors."""

    pass


class BulkValidationError(BulkException):
    """Raised when a bulk request is invalid."""

    pass


class BulkExecutionError(BulkException):
    """Raised when a bulk item fails during execution."""

    pass


class BulkRollbackError(BulkException):
    """Raised when rollback cannot restore a bulk batch."""

    pass


class BulkCancellationError(BulkException):
    """Raised when a batch is cancelled before completion."""

    pass
