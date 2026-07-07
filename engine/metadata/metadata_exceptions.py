from __future__ import annotations


class MetadataException(Exception):
    """Base exception for metadata extraction errors."""

    pass


class MetadataExtractionError(MetadataException):
    """Raised when metadata extraction fails for a file."""

    pass


class UnsupportedImageFormatError(MetadataException):
    """Raised when image format is not supported."""

    pass


class CorruptedImageError(MetadataException):
    """Raised when image file is corrupted or unreadable."""

    pass


class MetadataPersistenceError(MetadataException):
    """Raised when persisting metadata to repository fails."""

    pass
