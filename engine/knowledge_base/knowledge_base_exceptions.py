from __future__ import annotations


class KnowledgeBaseException(Exception):
    """Base exception for knowledge-base subsystem failures."""


class KnowledgeBaseNotFoundError(KnowledgeBaseException):
    """Raised when a requested dataset, series, or character does not exist."""


class KnowledgeBaseDuplicateError(KnowledgeBaseException):
    """Raised when an import or create operation would create a duplicate record."""


class KnowledgeBaseValidationError(KnowledgeBaseException):
    """Raised when knowledge-base data fails validation."""


class KnowledgeBaseImportError(KnowledgeBaseException):
    """Raised when importing JSON, CSV, or YAML-ready data fails."""


class KnowledgeBaseExportError(KnowledgeBaseException):
    """Raised when exporting knowledge-base data fails."""


class KnowledgeBaseSearchError(KnowledgeBaseException):
    """Raised when knowledge-base search cannot be completed."""
