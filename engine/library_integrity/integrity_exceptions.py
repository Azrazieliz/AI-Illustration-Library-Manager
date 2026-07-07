from __future__ import annotations


class IntegrityError(Exception):
    """Base exception for library integrity operations."""


class IntegrityValidationError(IntegrityError):
    """Raised when a scan request is invalid."""


class IntegrityCancelledError(IntegrityError):
    """Raised when a scan was cancelled before completion."""
