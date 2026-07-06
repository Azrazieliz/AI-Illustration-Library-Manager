from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from engine.database.database import get_database_manager


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    manager = get_database_manager()
    session = manager.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """Return a configured database session."""
    return get_database_manager().session_factory()
