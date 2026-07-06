from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from engine.config import settings
from engine.database.base import BaseModel


class DatabaseManager:
    """Singleton manager for database initialization and session handling."""

    _instance: "DatabaseManager | None" = None

    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def engine(self) -> Engine:
        """Return the configured SQLAlchemy engine."""
        if self._engine is None:
            self.initialize()
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        """Return the configured session factory."""
        if self._session_factory is None:
            self.initialize()
        return self._session_factory

    def initialize(self) -> Engine:
        """Create the engine, session factory, and tables if needed."""
        if self._engine is None:
            database_path = Path(settings.workspace) / settings.database_directory / "library.sqlite"
            database_path.parent.mkdir(parents=True, exist_ok=True)
            connection_url = f"sqlite:///{database_path.resolve()}"
            self._engine = create_engine(connection_url, future=True, echo=False)
            self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)
            self.create_tables()
        return self._engine

    def create_tables(self) -> None:
        """Create all database tables."""
        BaseModel.metadata.create_all(bind=self.engine)

    def drop_tables(self) -> None:
        """Drop all database tables."""
        BaseModel.metadata.drop_all(bind=self.engine)

    def vacuum(self) -> None:
        """Run SQLite VACUUM to reclaim space."""
        with self.engine.begin() as connection:
            connection.execute(text("VACUUM"))

    def health_check(self) -> bool:
        """Return True when the database is reachable."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


def get_database_manager() -> DatabaseManager:
    """Return the shared database manager singleton."""
    return database_manager


database_manager = DatabaseManager()
