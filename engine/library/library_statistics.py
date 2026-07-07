from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class LibraryStatistics:
    processed_at: datetime = datetime.now(timezone.utc)
