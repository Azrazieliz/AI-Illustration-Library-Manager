from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock


@dataclass(slots=True)
class Notification:
    title: str
    message: str
    level: str = "info"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationCenter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: list[Notification] = []

    def notify(self, title: str, message: str, *, level: str = "info") -> Notification:
        item = Notification(title=title, message=message, level=level)
        with self._lock:
            self._items.append(item)
        return item

    def list_notifications(self) -> list[Notification]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
