from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from sqlalchemy.orm import Session, scoped_session

from engine.database.database import get_database_manager


_active_session: ContextVar[Session | None] = ContextVar("active_db_session", default=None)
_scoped_registry: scoped_session[Session] | None = None
_scoped_factory_id: int | None = None


def _get_scoped_registry() -> scoped_session[Session]:
    global _scoped_registry, _scoped_factory_id
    manager = get_database_manager()
    factory = manager.session_factory
    factory_id = id(factory)

    if _scoped_registry is not None and _scoped_factory_id != factory_id:
        _scoped_registry.remove()
        _scoped_registry = None

    if _scoped_registry is None:
        _scoped_registry = scoped_session(factory)
        _scoped_factory_id = factory_id

    return _scoped_registry


@contextmanager
def use_session(session: Session) -> Iterator[Session]:
    """Bind repositories created in this scope to *session*."""
    token = _active_session.set(session)
    try:
        yield session
    finally:
        _active_session.reset(token)


class UnitOfWork:
    """Shared-session unit of work for cross-repository operations."""

    def __init__(self, session: Session | None = None) -> None:
        self._provided_session = session
        self.session: Session | None = None
        self._token = None
        self._owns_session = session is None

    def __enter__(self) -> Session:
        manager = get_database_manager()
        self.session = self._provided_session or manager.session_factory()
        self._token = _active_session.set(self.session)
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.session is None:
            return
        try:
            if self._owns_session:
                if exc is None:
                    self.session.commit()
                else:
                    self.session.rollback()
        finally:
            if self._token is not None:
                _active_session.reset(self._token)
            if self._owns_session:
                self.session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    manager = get_database_manager()
    session = manager.session_factory()
    with use_session(session):
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def get_session() -> Session:
    """Return a configured shared session for the current operation scope."""
    active = _active_session.get()
    if active is not None:
        return active
    return _get_scoped_registry()()


def remove_scoped_session() -> None:
    """Clear the thread-local shared session."""
    registry = _get_scoped_registry()
    registry.remove()
