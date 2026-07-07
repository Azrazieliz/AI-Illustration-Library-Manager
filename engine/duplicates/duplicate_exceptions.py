from __future__ import annotations


class DuplicateEngineError(Exception):
    """Base exception for duplicate engine failures."""


class DuplicateComparisonError(DuplicateEngineError):
    """Raised when a pairwise comparison cannot be completed."""


class DuplicatePersistenceError(DuplicateEngineError):
    """Raised when persisting a duplicate pair to the repository fails."""


class InvalidHashError(DuplicateEngineError):
    """Raised when a hash value is malformed and cannot be used for distance computation."""
