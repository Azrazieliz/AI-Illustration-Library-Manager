from __future__ import annotations

from typing import Protocol


class EmbeddingPlugin(Protocol):
    """Interface for future embedding providers."""

    def embed(self, source_path: str) -> str: ...
