from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ScanStatus(str, Enum):
    """Lifecycle status for a scanner run."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass(slots=True)
class ScanTarget:
    """A target root for a scan operation."""

    path: Path
    recursive: bool = True


@dataclass(slots=True)
class ScanEvent:
    """Event payload for scanner state changes."""

    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)
