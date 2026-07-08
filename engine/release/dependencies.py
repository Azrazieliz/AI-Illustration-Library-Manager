from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata


@dataclass(slots=True)
class DependencyValidationResult:
    installed: dict[str, str]
    missing: list[str]


_RUNTIME_DEPENDENCIES = [
    "sqlalchemy",
    "alembic",
    "pydantic",
    "pydantic-settings",
    "numpy",
    "opencv-python",
    "pillow",
    "faiss-cpu",
    "onnxruntime",
    "pyyaml",
    "structlog",
    "watchdog",
    "typer",
    "rich",
]


def validate_runtime_dependencies() -> DependencyValidationResult:
    installed: dict[str, str] = {}
    missing: list[str] = []
    for package in _RUNTIME_DEPENDENCIES:
        try:
            installed[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            missing.append(package)
    return DependencyValidationResult(installed=installed, missing=missing)
