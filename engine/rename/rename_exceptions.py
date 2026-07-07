from __future__ import annotations


class RenameException(Exception):
    """Base exception for rename subsystem errors."""

    pass


class RenameTemplateError(RenameException):
    """Raised when a rename template cannot be expanded."""

    pass


class RenamePreviewError(RenameException):
    """Raised when preview generation fails."""

    pass


class RenameApplyError(RenameException):
    """Raised when filesystem rename application fails."""

    pass


class RenameRollbackError(RenameException):
    """Raised when rollback for a rename batch fails."""

    pass
