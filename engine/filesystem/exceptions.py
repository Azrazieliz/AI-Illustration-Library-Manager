from __future__ import annotations


class TransactionError(Exception):
    """Base exception for filesystem transaction failures."""


class ConflictError(TransactionError):
    """Raised when a filesystem operation would overwrite an existing path."""


class RollbackError(TransactionError):
    """Raised when a rollback cannot be completed."""


class PreviewError(TransactionError):
    """Raised when a preview cannot be generated."""
