from __future__ import annotations


class AdaptiveLearningError(Exception):
    """Base exception for adaptive learning operations."""


class AdaptiveValidationError(AdaptiveLearningError):
    """Raised for invalid adaptive-learning payloads."""


class AdaptiveProfileNotFoundError(AdaptiveLearningError):
    """Raised when an adaptive profile cannot be found."""


class AdaptiveStorageLimitError(AdaptiveLearningError):
    """Raised when adaptive-learning persisted state exceeds storage limits."""


class AdaptivePersistenceCorruptionError(AdaptiveLearningError):
    """Raised when compressed adaptive state cannot be decoded safely."""


class AdaptiveCheckpointError(AdaptiveLearningError):
    """Raised for worker checkpoint and resume errors."""
