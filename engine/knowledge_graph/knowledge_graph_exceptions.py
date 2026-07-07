from __future__ import annotations


class KnowledgeGraphException(Exception):
    """Base exception for knowledge graph subsystem errors."""


class KnowledgeGraphBackendError(KnowledgeGraphException):
    """Raised when backend operations fail."""


class KnowledgeGraphBuildError(KnowledgeGraphException):
    """Raised when graph construction fails for an input record."""


class KnowledgeGraphQueryError(KnowledgeGraphException):
    """Raised when graph traversal/query operations fail."""


class KnowledgeGraphPersistenceError(KnowledgeGraphException):
    """Raised when repository interactions fail."""
