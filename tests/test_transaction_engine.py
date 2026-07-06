from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.filesystem.exceptions import ConflictError, PreviewError
from engine.filesystem.transaction_engine import TransactionEngine


@pytest.fixture()
def transaction_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TransactionEngine:
    monkeypatch.setattr(settings, "workspace", tmp_path)
    monkeypatch.setattr(settings, "database_directory", Path("database"))
    monkeypatch.setattr(settings, "log_directory", tmp_path / "logs")
    monkeypatch.setattr(settings, "cache_directory", tmp_path / "cache")
    monkeypatch.setattr(settings, "thumbnail_directory", tmp_path / "cache" / "thumbnails")
    monkeypatch.setattr(settings, "embedding_directory", tmp_path / "cache" / "embeddings")
    monkeypatch.setattr(settings, "knowledge_directory", tmp_path / "knowledge")
    monkeypatch.setattr(settings, "models_directory", tmp_path / "models")
    monkeypatch.setattr(settings, "datasets_directory", tmp_path / "datasets")

    database_manager._engine = None
    database_manager._session_factory = None
    database_manager._initialized = False
    database_manager.__init__()

    return TransactionEngine()


def test_preview_move_reports_conflicts(transaction_engine: TransactionEngine, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("hello", encoding="utf-8")
    destination.write_text("existing", encoding="utf-8")

    preview = transaction_engine.preview_move(source, destination)

    assert preview.operation == "move"
    assert preview.conflicts
    assert preview.estimated_result == "blocked"


def test_move_and_undo(transaction_engine: TransactionEngine, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("hello", encoding="utf-8")

    result = transaction_engine.move(source, destination)

    assert result is True
    assert destination.exists()
    assert not source.exists()

    undone = transaction_engine.undo()

    assert undone is True
    assert source.exists()
    assert not destination.exists()


def test_rename(transaction_engine: TransactionEngine, tmp_path: Path) -> None:
    source = tmp_path / "old_name.txt"
    source.write_text("hello", encoding="utf-8")

    result = transaction_engine.rename(source, tmp_path / "new_name.txt")

    assert result is True
    assert (tmp_path / "new_name.txt").exists()
    assert not source.exists()


def test_rollback_reverts_last_transaction(transaction_engine: TransactionEngine, tmp_path: Path) -> None:
    source = tmp_path / "rollback_source.txt"
    destination = tmp_path / "rollback_target.txt"
    source.write_text("rollback", encoding="utf-8")

    transaction_engine.move(source, destination)
    rolled_back = transaction_engine.rollback()

    assert rolled_back is True
    assert source.exists()
    assert not destination.exists()


def test_copy_detects_conflict(transaction_engine: TransactionEngine, tmp_path: Path) -> None:
    source = tmp_path / "copy_source.txt"
    destination = tmp_path / "copy_target.txt"
    source.write_text("copy", encoding="utf-8")
    destination.write_text("existing", encoding="utf-8")

    with pytest.raises(ConflictError):
        transaction_engine.copy(source, destination)
