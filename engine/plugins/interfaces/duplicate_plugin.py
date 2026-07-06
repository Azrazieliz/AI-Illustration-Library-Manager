from __future__ import annotations

from typing import Protocol


class DuplicatePlugin(Protocol):
    """Interface for future duplicate detection providers."""

    def detect(self, source_path: str) -> str: ...
