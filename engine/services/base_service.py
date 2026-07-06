from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy.orm import Session

from engine.database import get_session
from engine.logging import get_logger

ModelT = TypeVar("ModelT")


class BaseService(Generic[ModelT]):
    """Common service functionality with session management and logging support."""

    def __init__(self, session: Session | None = None) -> None:
        self.session = session or get_session()
        self.logger = get_logger(self.__class__.__name__)

    def commit(self) -> None:
        """Commit the current session."""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback the current session."""
        self.session.rollback()

    def close(self) -> None:
        """Close the current session."""
        self.session.close()

    def transaction(self, func: Any) -> Any:
        """Run a function inside a session transaction with rollback on failure."""
        try:
            result = func(self)
            self.commit()
            return result
        except Exception:
            self.rollback()
            raise

    def add(self, instance: ModelT) -> ModelT:
        """Add an instance to the session."""
        self.session.add(instance)
        return instance

    def flush(self) -> None:
        """Flush pending changes to the session."""
        self.session.flush()

    def refresh(self, instance: ModelT) -> None:
        """Refresh an instance from the database."""
        self.session.refresh(instance)

    def get_by_id(self, model_type: type[ModelT], identifier: int) -> ModelT | None:
        """Retrieve a model instance by primary key."""
        return self.session.get(model_type, identifier)

    def list_all(self, model_type: type[ModelT]) -> list[ModelT]:
        """List all instances of a model type."""
        return list(self.session.query(model_type).all())

    def delete(self, instance: ModelT) -> None:
        """Delete an instance from the session."""
        self.session.delete(instance)
