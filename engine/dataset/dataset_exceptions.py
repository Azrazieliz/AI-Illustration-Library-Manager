from __future__ import annotations


class DatasetException(Exception):
    """Base exception for dataset engine failures."""


class DatasetBuildError(DatasetException):
    """Raised when canonical dataset entry construction fails."""


class DatasetPersistenceError(DatasetException):
    """Raised when dataset entries cannot be persisted."""


class DatasetBackendError(DatasetException):
    """Raised when backend operations fail."""
