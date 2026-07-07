from __future__ import annotations


class SearchException(Exception):
    """Base exception for semantic search subsystem errors."""


class SearchBackendError(SearchException):
    """Raised when search backend operations fail."""


class SearchIndexingError(SearchException):
    """Raised when indexing of semantic records fails."""


class SearchQueryError(SearchException):
    """Raised when search query execution fails."""


class SearchPersistenceError(SearchException):
    """Raised when search records cannot be persisted via repository."""
