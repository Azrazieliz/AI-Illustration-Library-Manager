from __future__ import annotations


class EmbeddingException(Exception):
    """Base exception for embedding operations."""

    pass


class EmbeddingGenerationError(EmbeddingException):
    """Raised when embedding generation fails."""

    pass


class ProviderError(EmbeddingException):
    """Raised when provider initialization or inference fails."""

    pass


class UnsupportedProviderError(EmbeddingException):
    """Raised when a provider is not supported or available."""

    pass


class EmbeddingCacheError(EmbeddingException):
    """Raised when embedding cache operations fail."""

    pass


class EmbeddingPersistenceError(EmbeddingException):
    """Raised when persisting embedding records fails."""

    pass
