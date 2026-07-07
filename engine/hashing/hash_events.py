from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class HashStarted:
    """Raised when the engine begins computing hashes for a file."""

    path: Path


@dataclass(slots=True)
class FileHashed:
    """Raised when all requested hashes for a file have been computed and persisted."""

    path: Path
    sha256: str


@dataclass(slots=True)
class HashFailed:
    """Raised when hash computation for a file fails."""

    path: Path
    error: str


@dataclass(slots=True)
class HashCompleted:
    """Raised when a batch hashing run finishes."""

    total: int
    failed: int
