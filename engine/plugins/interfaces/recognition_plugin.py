from __future__ import annotations

from typing import Protocol


class RecognitionPlugin(Protocol):
    """Interface for future recognition providers."""

    def recognize(self, source_path: str) -> str: ...
