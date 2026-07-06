from __future__ import annotations

from typing import Protocol


class DatasetExportPlugin(Protocol):
    """Interface for future dataset export providers."""

    def export(self, source_path: str) -> str: ...
