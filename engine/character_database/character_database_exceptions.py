from __future__ import annotations


class CharacterDatabaseError(Exception):
    """Base exception for character database operations."""


class CharacterNotFoundError(CharacterDatabaseError):
    """Raised when a character id cannot be resolved."""


class SeriesNotFoundError(CharacterDatabaseError):
    """Raised when a series id cannot be resolved."""


class MergeConflictError(CharacterDatabaseError):
    """Raised when a merge operation cannot be completed safely."""


class CharacterDatabaseValidationError(CharacterDatabaseError):
    """Raised when validation fails under strict mode."""
