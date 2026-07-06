from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PreviewTransaction:
    """Preview of a pending filesystem transaction."""

    source: Path
    destination: Path
    operation: str
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    estimated_result: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the preview to a dictionary."""
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "operation": self.operation,
            "conflicts": self.conflicts,
            "warnings": self.warnings,
            "estimated_result": self.estimated_result,
        }
