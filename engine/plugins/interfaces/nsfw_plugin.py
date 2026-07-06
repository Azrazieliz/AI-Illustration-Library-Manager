from __future__ import annotations

from typing import Protocol


class NSFWPlugin(Protocol):
    """Interface for future NSFW classification providers."""

    def classify(self, source_path: str) -> str: ...
