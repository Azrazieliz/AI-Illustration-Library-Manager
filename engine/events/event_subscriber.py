from __future__ import annotations

from typing import Callable

from engine.events.base_event import BaseEvent


class EventSubscriber:
    """Minimal subscriber abstraction for architecture-level event handling."""

    def __init__(self, handler: Callable[[BaseEvent], None]) -> None:
        self.handler = handler

    def __call__(self, event: BaseEvent) -> None:
        self.handler(event)
