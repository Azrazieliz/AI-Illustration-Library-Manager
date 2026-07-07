from __future__ import annotations


class AdvancedSearchException(Exception):
    """Base exception for advanced search failures."""


class AdvancedSearchQueryError(AdvancedSearchException):
    """Raised when a search query is invalid."""


class AdvancedSearchParseError(AdvancedSearchException):
    """Raised when boolean query parsing fails."""


class AdvancedSearchPersistenceError(AdvancedSearchException):
    """Raised when repository persistence interactions fail."""
