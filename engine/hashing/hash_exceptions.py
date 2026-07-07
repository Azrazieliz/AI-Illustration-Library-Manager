from __future__ import annotations


class HashEngineError(Exception):
    """Base exception for hash engine failures."""


class HashComputationError(HashEngineError):
    """Raised when hash computation fails for a specific file."""


class UnsupportedImageFormatError(HashEngineError):
    """Raised when a file cannot be opened as an image for perceptual hashing."""


class HashPersistenceError(HashEngineError):
    """Raised when persisting a hash result to the repository fails."""
