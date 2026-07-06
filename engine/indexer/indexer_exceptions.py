from __future__ import annotations


class IndexerError(Exception):
    """Base exception for incremental indexer failures."""


class IndexerInterruptedError(IndexerError):
    """Raised when indexing is interrupted and must resume safely."""
