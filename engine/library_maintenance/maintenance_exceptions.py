from __future__ import annotations


class MaintenanceError(Exception):
    """Base exception for maintenance operations."""


class MaintenanceValidationError(MaintenanceError):
    """Raised for invalid maintenance inputs."""


class MaintenanceJobNotFoundError(MaintenanceError):
    """Raised when a maintenance job id does not exist."""
