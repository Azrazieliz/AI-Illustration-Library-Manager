from __future__ import annotations


class ExportException(Exception):
    """Base exception for dataset export failures."""


class ExportBuildError(ExportException):
    """Raised when export record construction fails."""


class ExportPersistenceError(ExportException):
    """Raised when export artifacts cannot be persisted."""


class ExportBackendError(ExportException):
    """Raised when export backend operations fail."""


class ExportFormatError(ExportException):
    """Raised when a requested export format is unsupported."""
