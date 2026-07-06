from __future__ import annotations

import os
import shutil
from pathlib import Path

from engine.filesystem.exceptions import ConflictError, TransactionError


class FileOperations:
    """Small filesystem wrapper around safe file operations."""

    @staticmethod
    def ensure_parent(path: Path) -> Path:
        """Ensure the parent directory exists."""
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def move(source: Path, destination: Path) -> None:
        """Move a file using an atomic replacement when possible."""
        if not source.exists():
            raise TransactionError(f"Source does not exist: {source}")
        if destination.exists():
            raise ConflictError(f"Destination already exists: {destination}")
        FileOperations.ensure_parent(destination)
        os.replace(source, destination)

    @staticmethod
    def rename(source: Path, destination: Path) -> None:
        """Rename a file using os.replace for atomic semantics."""
        FileOperations.move(source, destination)

    @staticmethod
    def copy(source: Path, destination: Path) -> None:
        """Copy a file, refusing to overwrite an existing destination."""
        if not source.exists():
            raise TransactionError(f"Source does not exist: {source}")
        if destination.exists():
            raise ConflictError(f"Destination already exists: {destination}")
        FileOperations.ensure_parent(destination)
        shutil.copy2(source, destination)

    @staticmethod
    def restore(source: Path, destination: Path) -> None:
        """Restore a file from a backup location to its destination."""
        FileOperations.move(source, destination)
