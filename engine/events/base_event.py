from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BaseEvent:
    """Base type for architecture-level domain events."""

    payload: dict[str, Any] | None = None
