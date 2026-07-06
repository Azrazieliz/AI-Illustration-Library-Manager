from __future__ import annotations

from typing import Callable

from engine.events.base_event import BaseEvent


class EventBus:
    """Simple in-process event bus for architecture-level decoupling."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[BaseEvent], None]] = []

    def subscribe(self, subscriber: Callable[[BaseEvent], None]) -> None:
        self._subscribers.append(subscriber)

    def publish(self, event: BaseEvent) -> None:
        for subscriber in list(self._subscribers):
            subscriber(event)
