from __future__ import annotations

from typing import Any, Generic, TypeVar

from engine.logging import get_logger
from engine.repositories.base_repository import BaseRepository

ModelT = TypeVar("ModelT")


class BaseService(Generic[ModelT]):
    """Common service functionality that delegates persistence to repositories."""

    def __init__(self, repository: BaseRepository[ModelT] | None = None) -> None:
        self.repository = repository
        self.logger = get_logger(self.__class__.__name__)

    def commit(self) -> None:
        if self.repository is not None:
            self.repository.commit()

    def rollback(self) -> None:
        if self.repository is not None:
            self.repository.rollback()

    def close(self) -> None:
        if self.repository is not None:
            self.repository.close()

    def transaction(self, func: Any) -> Any:
        try:
            result = func(self)
            self.commit()
            return result
        except Exception:
            self.rollback()
            raise

    def add(self, instance: ModelT) -> ModelT:
        if self.repository is None:
            raise RuntimeError("No repository configured for this service")
        return self.repository.add(instance)

    def flush(self) -> None:
        if self.repository is not None:
            self.repository.flush()

    def refresh(self, instance: ModelT) -> None:
        if self.repository is not None:
            self.repository.refresh(instance)

    def get_by_id(self, model_type: type[ModelT], identifier: int) -> ModelT | None:
        if self.repository is None:
            return None
        return self.repository.get_by_id(identifier)

    def list_all(self, model_type: type[ModelT]) -> list[ModelT]:
        if self.repository is None:
            return []
        return self.repository.list_all()

    def delete(self, instance: ModelT) -> None:
        if self.repository is not None:
            self.repository.delete(instance)
