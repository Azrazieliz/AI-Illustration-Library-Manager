from __future__ import annotations

from typing import Protocol


class VLMPlugin(Protocol):
    """Interface for future VLM providers."""

    def analyze(self, source_path: str) -> str: ...
