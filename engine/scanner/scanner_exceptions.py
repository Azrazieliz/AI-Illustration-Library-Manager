from __future__ import annotations


class ScannerError(Exception):
    """Base exception for scanner failures."""


class ScanCancelledError(ScannerError):
    """Raised when a scan is cancelled before completion."""


class UnsupportedFileError(ScannerError):
    """Raised for files that are not supported by the scanner."""
