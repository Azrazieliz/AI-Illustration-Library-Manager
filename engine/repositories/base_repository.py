from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from engine.database.session import get_session

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """Repository wrapper around session-based persistence."""

    def __init__(self, model_type: type[ModelT], session: Session | None = None) -> None:
        self.model_type = model_type
        self.session = session or get_session()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()

    def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        return instance

    def flush(self) -> None:
        self.session.flush()

    def refresh(self, instance: ModelT) -> None:
        self.session.refresh(instance)

    def get_by_id(self, identifier: int) -> ModelT | None:
        return self.session.get(self.model_type, identifier)

    def list_all(self) -> list[ModelT]:
        return list(self.session.query(self.model_type).all())

    def delete(self, instance: ModelT) -> None:
        self.session.delete(instance)
