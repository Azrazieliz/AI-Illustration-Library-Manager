from __future__ import annotations


class ThumbnailEngineError(Exception):
    """Base exception for thumbnail engine failures."""


class ThumbnailGenerationError(ThumbnailEngineError):
    """Raised when Pillow cannot generate a thumbnail for an image."""


class CorruptedImageError(ThumbnailEngineError):
    """Raised when an image file cannot be opened or decoded."""


class UnsupportedFormatError(ThumbnailEngineError):
    """Raised when the image format is not supported for thumbnail generation."""


class ThumbnailPersistenceError(ThumbnailEngineError):
    """Raised when storing thumbnail metadata in the repository fails."""
