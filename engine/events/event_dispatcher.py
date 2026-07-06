from __future__ import annotations

from typing import Callable

from engine.events.base_event import BaseEvent
from engine.events.event_bus import EventBus


class EventDispatcher:
    """Dispatcher that publishes events to subscribers through an event bus."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus or EventBus()

    def dispatch(self, event: BaseEvent) -> None:
        self.bus.publish(event)

    def subscribe(self, subscriber: Callable[[BaseEvent], None]) -> None:
        self.bus.subscribe(subscriber)
