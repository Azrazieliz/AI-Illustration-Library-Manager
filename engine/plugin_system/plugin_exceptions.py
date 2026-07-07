from __future__ import annotations


class PluginSystemException(Exception):
    """Base exception for plugin system failures."""


class PluginManifestError(PluginSystemException):
    """Raised when plugin manifest parsing or validation fails."""


class PluginCompatibilityError(PluginSystemException):
    """Raised when plugin/app or dependency versions are incompatible."""


class PluginDependencyError(PluginSystemException):
    """Raised when dependency resolution fails."""


class PluginLoadError(PluginSystemException):
    """Raised when loading a plugin module fails."""


class PluginPermissionError(PluginSystemException):
    """Raised when plugin executes an operation without permission."""
