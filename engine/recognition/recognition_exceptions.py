from __future__ import annotations


class RecognitionException(Exception):
    """Base exception for recognition subsystem errors."""


class RecognitionProviderError(RecognitionException):
    """Raised when a recognition provider cannot process an input."""


class UnsupportedRecognitionProviderError(RecognitionProviderError):
    """Raised when a provider type is not supported."""


class RecognitionPersistenceError(RecognitionException):
    """Raised when recognized data cannot be persisted."""
