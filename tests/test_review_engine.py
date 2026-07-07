"""Tests for the Review Queue Foundation (Commit 0026)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.review import (
    ReviewDecisionType,
    ReviewEngine,
    ReviewStatus,
)
from engine.repositories.review_repository import ReviewRepository


@pytest.fixture()
def review_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace", tmp_path)
    monkeypatch.setattr(settings, "database_directory", Path("database"))
    monkeypatch.setattr(settings, "log_directory", tmp_path / "logs")
    monkeypatch.setattr(settings, "cache_directory", tmp_path / "cache")
    monkeypatch.setattr(settings, "thumbnail_directory", tmp_path / "cache" / "thumbnails")
    monkeypatch.setattr(settings, "embedding_directory", tmp_path / "cache" / "embeddings")
    monkeypatch.setattr(settings, "knowledge_directory", tmp_path / "knowledge")
    monkeypatch.setattr(settings, "models_directory", tmp_path / "models")
    monkeypatch.setattr(settings, "datasets_directory", tmp_path / "datasets")
    monkeypatch.setattr(settings, "max_background_workers", 2)

    database_manager._engine = None
    database_manager._session_factory = None
    database_manager._initialized = False
    database_manager.__init__()
    ReviewRepository.reset_state()


def _make_engine() -> ReviewEngine:
    return ReviewEngine(repository=ReviewRepository())


def test_create_item(review_env: None, tmp_path: Path) -> None:
    engine = _make_engine()
    item = engine.create_review_item(
        image_id=1,
        source_path=tmp_path / "fate.png",
        operation_type="recognition",
        confidence=0.82,
        proposed_value={"series": "Fate"},
        current_value={"series": None},
        series="Fate",
        character="Saber",
    )

    assert item.review_id == 1
    assert item.status is ReviewStatus.PENDING
    assert engine.statistics.total == 1
    assert engine.statistics.pending_count == 1


def test_approve_reject_skip(review_env: None, tmp_path: Path) -> None:
    engine = _make_engine()
    approve_item = engine.create_review_item(
        image_id=1,
        source_path=tmp_path / "approve.png",
        operation_type="rename",
        confidence=0.7,
        proposed_value="Fate_Saber.png",
        current_value="fate.png",
        series="Fate",
        character="Saber",
    )
    reject_item = engine.create_review_item(
        image_id=2,
        source_path=tmp_path / "reject.png",
        operation_type="organizer",
        confidence=0.6,
        proposed_value="/Fate/Saber",
        current_value="/Unsorted",
        series="Fate",
        character="Saber",
    )
    skip_item = engine.create_review_item(
        image_id=3,
        source_path=tmp_path / "skip.png",
        operation_type="recognition",
        confidence=0.5,
        proposed_value="Fate",
        current_value="unknown",
        series="Fate",
        character="Saber",
    )

    approve = engine.approve_review(approve_item.review_id, reviewer="alice", reason="valid")
    reject = engine.reject_review(reject_item.review_id, reviewer="bob", reason="wrong")
    skip = engine.skip_review(skip_item.review_id, reviewer="carol", reason="uncertain")

    assert approve.new_status is ReviewStatus.APPROVED
    assert reject.new_status is ReviewStatus.REJECTED
    assert skip.new_status is ReviewStatus.SKIPPED
    assert engine.statistics.pending_count == 0
    assert engine.statistics.approved_count == 1
    assert engine.statistics.rejected_count == 1
    assert engine.statistics.skipped_count == 1


def test_bulk_approve_and_reject(review_env: None, tmp_path: Path) -> None:
    engine = _make_engine()
    approve_ids = []
    reject_ids = []
    for index in range(2):
        approve_item = engine.create_review_item(
            image_id=10 + index,
            source_path=tmp_path / f"approve-{index}.png",
            operation_type="recognition",
            confidence=0.8,
            proposed_value="Fate",
            current_value="unknown",
            series="Fate",
            character="Saber",
        )
        approve_ids.append(approve_item.review_id)
    for index in range(2):
        reject_item = engine.create_review_item(
            image_id=20 + index,
            source_path=tmp_path / f"reject-{index}.png",
            operation_type="rename",
            confidence=0.4,
            proposed_value="bad",
            current_value="good",
            series="Fate",
            character="Rin",
        )
        reject_ids.append(reject_item.review_id)

    approve_result = engine.bulk_approve(approve_ids, reviewer="alice", reason="ok")
    reject_result = engine.bulk_reject(reject_ids, reviewer="bob", reason="nope")

    assert approve_result.applied is True
    assert reject_result.applied is True
    assert len(approve_result.decisions) == 2
    assert len(reject_result.decisions) == 2
    assert engine.statistics.approved_count == 2
    assert engine.statistics.rejected_count == 2


def test_filters_sorting_pagination(review_env: None, tmp_path: Path) -> None:
    engine = _make_engine()
    first = engine.create_review_item(
        image_id=1,
        source_path=tmp_path / "a.png",
        operation_type="recognition",
        confidence=0.4,
        proposed_value="A",
        current_value="B",
        series="Bleach",
        character="Rukia",
    )
    second = engine.create_review_item(
        image_id=2,
        source_path=tmp_path / "b.png",
        operation_type="rename",
        confidence=0.9,
        proposed_value="C",
        current_value="D",
        series="Fate",
        character="Saber",
    )
    third = engine.create_review_item(
        image_id=3,
        source_path=tmp_path / "c.png",
        operation_type="organization",
        confidence=0.6,
        proposed_value="E",
        current_value="F",
        series="Fate",
        character="Rin",
    )

    third.timestamp = datetime.now(timezone.utc) - timedelta(days=2)
    first.timestamp = datetime.now(timezone.utc) - timedelta(days=1)

    filtered = engine.filter_reviews(operation_type="rename", series="Fate", character="Saber")
    assert len(filtered) == 1
    assert filtered[0].review_id == second.review_id

    sorted_items = engine.sort_reviews([first, second, third], sort_by="confidence", descending=True)
    assert [item.review_id for item in sorted_items] == [second.review_id, third.review_id, first.review_id]

    paginated = engine.paginate_reviews(sorted_items, page=2, page_size=1)
    assert paginated.total == 3
    assert paginated.page == 2
    assert paginated.page_size == 1
    assert len(paginated.items) == 1

    date_filtered = engine.filter_reviews(date_from=datetime.now(timezone.utc) - timedelta(days=1, hours=1))
    assert second.review_id in {item.review_id for item in date_filtered}


def test_statistics(review_env: None, tmp_path: Path) -> None:
    engine = _make_engine()
    item = engine.create_review_item(
        image_id=1,
        source_path=tmp_path / "stats.png",
        operation_type="recognition",
        confidence=0.75,
        proposed_value="Fate",
        current_value="unknown",
        series="Fate",
        character="Saber",
    )
    engine.approve_review(item.review_id, reviewer="alice", reason="ok")

    assert engine.statistics.total == 1
    assert engine.statistics.pending_count == 0
    assert engine.statistics.approved_count == 1
    assert engine.statistics.average_confidence == 0.75
    assert engine.statistics.completion_percentage == 100.0


def test_rollback_history(review_env: None, tmp_path: Path) -> None:
    engine = _make_engine()
    first = engine.create_review_item(
        image_id=1,
        source_path=tmp_path / "rollback-a.png",
        operation_type="rename",
        confidence=0.8,
        proposed_value="A",
        current_value="B",
        series="Fate",
        character="Saber",
    )
    second = engine.create_review_item(
        image_id=2,
        source_path=tmp_path / "rollback-b.png",
        operation_type="rename",
        confidence=0.8,
        proposed_value="C",
        current_value="D",
        series="Fate",
        character="Rin",
    )

    batch = engine.create_batch([first.review_id, second.review_id])
    assert batch.batch_id

    engine.bulk_approve([first.review_id, second.review_id], reviewer="alice", reason="ok")
    history = engine.repository.get_decision_history(first.review_id)
    assert len(history) == 1
    assert history[0].new_status is ReviewStatus.APPROVED

    rollback = engine.rollback_last_batch()
    assert rollback is not None
    assert rollback.rolled_back is True

    restored_first = engine.repository.get_review_item(first.review_id)
    assert restored_first is not None
    assert restored_first.status is ReviewStatus.PENDING
    assert restored_first.current_value == "B"


def test_duplicate_review_prevention(review_env: None, tmp_path: Path) -> None:
    engine = _make_engine()
    first = engine.create_review_item(
        image_id=1,
        source_path=tmp_path / "dup.png",
        operation_type="recognition",
        confidence=0.5,
        proposed_value="Fate",
        current_value="unknown",
        series="Fate",
        character="Saber",
    )
    second = engine.create_review_item(
        image_id=1,
        source_path=tmp_path / "dup.png",
        operation_type="recognition",
        confidence=0.5,
        proposed_value="Fate",
        current_value="unknown",
        series="Fate",
        character="Saber",
    )

    assert first.review_id == second.review_id
    assert len(engine.repository.list_review_items()) == 1
