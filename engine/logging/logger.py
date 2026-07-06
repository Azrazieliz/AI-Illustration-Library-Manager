from __future__ import annotations

import logging
from typing import Any

from engine.logging.manager import get_logger


class LoggerAdapter(logging.LoggerAdapter):
    """Adapter that exposes a simple interface for application modules."""

    def __init__(self, logger: logging.Logger | None = None, extra: dict[str, Any] | None = None) -> None:
        super().__init__(logger or get_logger(), extra or {})

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:  # noqa: A003
        """Log an exception with traceback information."""
        self.error(msg, *args, exc_info=True, **kwargs)


class AppLogger(LoggerAdapter):
    """Concrete application logger compatible with the package API."""

    def __init__(self, name: str) -> None:
        super().__init__(get_logger(name))
