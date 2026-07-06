from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from typing import Any

from rich.logging import RichHandler


class LogFormatter(logging.Formatter):
    """Base formatter for human-readable log output."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        return f"{timestamp} [{record.levelname}] {record.name}: {record.getMessage()}"


class ConsoleFormatter(LogFormatter):
    """Formatter used for console output."""


class JsonFormatter(logging.Formatter):
    """Formatter that emits structured JSON log lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class RichConsoleHandler(RichHandler):
    """Console handler with rich coloring and tracebacks."""

    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(
            level=level,
            rich_tracebacks=True,
            show_time=False,
            show_path=False,
            markup=False,
        )
        self.setFormatter(ConsoleFormatter())


class JsonRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating file handler that writes newline-delimited JSON."""

    def __init__(
        self,
        filename: str,
        maxBytes: int = 10 * 1024 * 1024,
        backupCount: int = 10,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(filename=filename, maxBytes=maxBytes, backupCount=backupCount, encoding=encoding)
        self.setFormatter(JsonFormatter())
