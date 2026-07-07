from __future__ import annotations


class AutomationException(Exception):
    """Base exception for automation failures."""


class AutomationValidationError(AutomationException):
    """Raised when automation definitions are invalid."""


class AutomationDependencyError(AutomationException):
    """Raised when dependency ordering cannot be resolved."""


class AutomationScheduleError(AutomationException):
    """Raised when schedule parsing or evaluation fails."""
