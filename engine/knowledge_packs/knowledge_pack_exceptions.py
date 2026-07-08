from __future__ import annotations


class KnowledgePackError(Exception):
    """Base exception for knowledge pack operations."""


class KnowledgePackValidationError(KnowledgePackError):
    """Raised for invalid knowledge pack payloads."""


class KnowledgePackNotFoundError(KnowledgePackError):
    """Raised when a knowledge pack id cannot be located."""


class KnowledgePackIntegrityError(KnowledgePackError):
    """Raised when checksum/signature/integrity validation fails."""


class KnowledgePackDependencyError(KnowledgePackError):
    """Raised when dependency constraints are not satisfied."""


class KnowledgePackConflictError(KnowledgePackError):
    """Raised when conflicts are detected and cannot be auto-resolved."""


class KnowledgePackStorageLimitError(KnowledgePackError):
    """Raised when installed knowledge pack storage exceeds the 5 GB limit."""


class KnowledgePackWorkerError(KnowledgePackError):
    """Raised when worker lifecycle or background processing fails."""
