from __future__ import annotations


class AndroidBridgeError(Exception):
    """Base exception for Android bridge failures."""


class AndroidCompatibilityError(AndroidBridgeError):
    """Raised when a requested operation is not supported by Android compatibility settings."""


class AndroidSerializationError(AndroidBridgeError):
    """Raised when DTO serialization or deserialization fails."""


class AndroidStorageError(AndroidBridgeError):
    """Raised for scoped storage, SAF, MediaStore, or URI adapter failures."""


class AndroidWorkerError(AndroidBridgeError):
    """Raised for Android worker scheduling or lifecycle failures."""
