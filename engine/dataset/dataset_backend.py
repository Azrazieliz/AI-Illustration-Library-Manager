from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from engine.dataset.dataset_models import DatasetEntry

if TYPE_CHECKING:
    from engine.repositories.dataset_repository import DatasetRepository


class DatasetBackend(ABC):
    """Abstract backend for canonical dataset entry storage."""

    @abstractmethod
    def get(self, image_id: int) -> DatasetEntry | None:
        """Retrieve existing entry for image id."""

    @abstractmethod
    def upsert(self, entry: DatasetEntry) -> bool:
        """Insert or update entry. Returns True if new entry was created."""


class InMemoryDatasetBackend(DatasetBackend):
    """Default in-memory backend for local runs and tests."""

    def __init__(self) -> None:
        self._entries: dict[int, DatasetEntry] = {}

    def get(self, image_id: int) -> DatasetEntry | None:
        return self._entries.get(image_id)

    def upsert(self, entry: DatasetEntry) -> bool:
        created = entry.image_id not in self._entries
        self._entries[entry.image_id] = entry
        return created


class PersistentDatasetBackend(DatasetBackend):
    """Durable backend that stores dataset artifacts by immutable Fusion UUID."""

    def __init__(self, repository: DatasetRepository | None = None) -> None:
        if repository is None:
            from engine.repositories.dataset_repository import DatasetRepository

            repository = DatasetRepository()
        self.repository = repository

    def get(self, image_id: int) -> DatasetEntry | None:
        return self.repository.get_dataset_entry(image_id)

    def upsert(self, entry: DatasetEntry) -> bool:
        return self.repository.upsert_dataset_entry(entry)
