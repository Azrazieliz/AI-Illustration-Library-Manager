from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
import traceback
from pathlib import Path
from typing import Any

import structlog

from engine.config import settings
from engine.logging.bootstrap import ensure_log_directory
from engine.logging.formatter import JsonRotatingFileHandler, RichConsoleHandler


class LoggerManager:
    """Central manager for application logging."""

    _instance: "LoggerManager | None" = None
    _initialized: bool = False

    def __new__(cls) -> "LoggerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._logger: logging.Logger | None = None
        self._configure_structlog()

    def _configure_structlog(self) -> None:
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    def configure(
        self,
        level: int | str | None = None,
        app_name: str | None = None,
        version: str | None = None,
    ) -> logging.Logger:
        """Configure the root logger with console and file handlers."""
        if self._logger is not None and self._logger.handlers:
            return self._logger

        resolved_level = self._resolve_level(level)
        resolved_app_name = app_name or settings.app_name
        resolved_version = version or settings.version

        log_directory = ensure_log_directory(settings.log_directory)
        log_file = log_directory / "application.log"
        json_log_file = log_directory / "application.json"

        root_logger = logging.getLogger()
        root_logger.setLevel(resolved_level)
        root_logger.propagate = False

        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()

        console_handler = RichConsoleHandler(level=resolved_level)
        console_handler.setLevel(resolved_level)
        root_logger.addHandler(console_handler)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        file_handler.setLevel(resolved_level)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root_logger.addHandler(file_handler)

        json_handler = JsonRotatingFileHandler(filename=str(json_log_file))
        json_handler.setLevel(resolved_level)
        root_logger.addHandler(json_handler)

        self._logger = root_logger

        self._log_startup_banner(resolved_app_name, resolved_version)
        return self._logger

    def get_logger(self, name: str | None = None) -> logging.Logger:
        """Return a configured logger for the given name."""
        if self._logger is None:
            self.configure()
        if name is None:
            return self._logger or logging.getLogger("application")
        return logging.getLogger(name)

    def shutdown(self) -> None:
        """Flush and close handlers and release resources."""
        if self._logger is None:
            return
        for handler in list(self._logger.handlers):
            handler.flush()
            handler.close()
            self._logger.removeHandler(handler)
        logging.shutdown()
        self._logger = None

    def report_exception(self, context: str, exc: Exception) -> None:
        logger = self.get_logger("diagnostics")
        logger.error(
            "Unhandled runtime exception",
            extra={
                "context": context,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            },
        )

    def _log_startup_banner(self, app_name: str, version: str) -> None:
        if self._logger is None:
            return
        self._logger.info("Startup configuration initialized")
        self._logger.info(
            "Application startup",
            extra={
                "app_name": app_name,
                "version": version,
                "python_version": sys.version.split()[0],
                "operating_system": platform.system(),
                "working_directory": str(Path.cwd()),
            },
        )

    @staticmethod
    def _resolve_level(level: int | str | None) -> int:
        if level is None:
            return logging.INFO
        if isinstance(level, str):
            normalized = level.upper()
            if normalized == "DEBUG":
                return logging.DEBUG
            if normalized == "INFO":
                return logging.INFO
            if normalized == "WARNING":
                return logging.WARNING
            if normalized == "ERROR":
                return logging.ERROR
            if normalized == "CRITICAL":
                return logging.CRITICAL
        return int(level)


manager = LoggerManager()


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a singleton logger instance for the given name."""
    return manager.get_logger(name)


def configure(level: int | str | None = None, app_name: str | None = None, version: str | None = None) -> logging.Logger:
    """Configure the singleton logger."""
    return manager.configure(level=level, app_name=app_name, version=version)


def shutdown() -> None:
    """Shutdown the singleton logger."""
    manager.shutdown()

