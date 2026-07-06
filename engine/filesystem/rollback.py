from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.filesystem.exceptions import RollbackError


class RollbackPlan:
    """Store the previous state of a transaction for safe rollback."""

    def __init__(self, source: Path, destination: Path, operation: str, completed: bool = False) -> None:
        self.source = source
        self.destination = destination
        self.operation = operation
        self.completed = completed

    def to_dict(self) -> dict[str, Any]:
        """Serialize the rollback plan to a dictionary."""
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "operation": self.operation,
            "completed": self.completed,
        }


class RollbackManager:
    """Apply rollback plans for filesystem operations."""

    def __init__(self) -> None:
        self._plans: list[RollbackPlan] = []

    def add(self, plan: RollbackPlan) -> None:
        """Record a rollback plan."""
        self._plans.append(plan)

    def pop(self) -> RollbackPlan:
        """Return the most recent rollback plan."""
        if not self._plans:
            raise RollbackError("No rollback plan available")
        return self._plans.pop()

    def clear(self) -> None:
        """Clear all recorded rollback plans."""
        self._plans.clear()
