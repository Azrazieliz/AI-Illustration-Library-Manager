"""Tests for the Bulk Operations Foundation (Commit 0027)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.bulk import BulkBatchStatus, BulkEngine, BulkItemStatus, BulkProgress
from engine.collections.collection_models import CollectionKind
from engine.config import settings
from engine.database.database import database_manager
from engine.database.models.image import Image
from engine.organizer import OrganizationRule
from engine.rename import RenameRule
from engine.repositories.collection_repository import CollectionRepository
from engine.repositories.bulk_repository import BulkRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.recognition_repository import RecognitionRepository
from engine.repositories.review_repository import ReviewRepository
from engine.repositories.tag_repository import TagRepository


@pytest.fixture()
def bulk_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    BulkRepository.reset_state()
    CollectionRepository.reset_state()
    ReviewRepository.reset_state()


def _register_image(path: Path, *, series: str | None = None, characters: list[str] | None = None, year: int | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")
    repo = ImageRepository()
    image = repo.create_image(original_path=str(path), filename=path.name, extension=path.suffix)
    if series or characters:
        recognition_repo = RecognitionRepository()
        db_image = recognition_repo.get_by_id(image.id)
        assert db_image is not None
        recognition_repo.apply_recognition(
            image=db_image,
            series_name=series,
            character_names=characters or [],
        )
    if year is not None:
        metadata_repo = MetadataRepository()
        metadata_repo.create_metadata_record(image_id=image.id, exif_data=json.dumps({"Year": year}))
    return image.id


def _make_engine(callback=None) -> BulkEngine:
    return BulkEngine(callback=callback)


def test_successful_batch_execution(bulk_env: None, tmp_path: Path) -> None:
    first_id = _register_image(tmp_path / "source" / "one.png")
    second_id = _register_image(tmp_path / "source" / "two.png")
    destination = tmp_path / "moved"

    engine = _make_engine()
    result = engine.move_images([second_id, first_id], destination)

    assert result.applied is True
    assert result.status is BulkBatchStatus.COMPLETED
    assert [item.entity_id for item in result.items] == [first_id, second_id]
    assert result.progress_percentage == 100.0
    assert engine.statistics.succeeded_items == 2
    assert (destination / "one.png").exists()
    assert (destination / "two.png").exists()


def test_partial_failures(bulk_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "source" / "partial.png")
    engine = _make_engine()
    result = engine.delete_images([image_id, 999999])

    assert result.failed == 1
    assert result.succeeded == 1
    assert result.status == BulkBatchStatus.PARTIAL
    assert engine.statistics.failed_items == 1
    assert engine.statistics.partial_failures == 1


def test_rollback(bulk_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "source" / "rollback.png")
    destination = tmp_path / "rolled"
    engine = _make_engine()

    result = engine.move_images([image_id], destination)
    moved_path = result.items[0].target_path
    assert moved_path is not None and moved_path.exists()

    rollback = engine.rollback_last_batch()
    assert rollback is not None
    assert rollback.rolled_back is True
    assert (tmp_path / "source" / "rollback.png").exists()
    assert moved_path is not None and not moved_path.exists()


def test_dry_run(bulk_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "source" / "dry.png")
    destination = tmp_path / "dry-run"
    engine = _make_engine()

    result = engine.copy_images([image_id], destination, dry_run=True)

    assert result.dry_run is True
    assert result.applied is False
    assert result.total == 1
    assert not destination.exists()
    assert (tmp_path / "source" / "dry.png").exists()


def test_resume_and_cancellation(bulk_env: None, tmp_path: Path) -> None:
    image_ids = [
        _register_image(tmp_path / "source" / f"resume-{index}.png")
        for index in range(3)
    ]
    destination = tmp_path / "resume"
    cancelled_once = {"value": False}
    engine_holder: dict[str, BulkEngine] = {}

    def callback(event: object) -> None:
        if isinstance(event, BulkProgress) and event.processed == 1 and not cancelled_once["value"]:
            cancelled_once["value"] = True
            engine_holder["engine"].cancel_batch(event.batch_id)

    engine = _make_engine(callback=callback)
    engine_holder["engine"] = engine

    result = engine.move_images(image_ids, destination)
    assert result.cancelled is True
    assert result.processed < result.total

    resumed = engine.resume_batch(result.batch_id)
    assert resumed.resumed is True
    assert resumed.cancelled is False
    assert resumed.status == BulkBatchStatus.COMPLETED
    assert all((destination / f"resume-{index}.png").exists() for index in range(3))


def test_progress_and_statistics(bulk_env: None, tmp_path: Path) -> None:
    image_ids = [_register_image(tmp_path / "source" / f"stats-{index}.png") for index in range(3)]
    engine = _make_engine()

    result = engine.assign_tags(image_ids, tag_name="popular", tag_category="mood")

    assert result.status == BulkBatchStatus.COMPLETED
    assert engine.statistics.processed_items == 3
    assert engine.statistics.succeeded_items == 3
    assert engine.statistics.progress_percentage == 100.0
    assert engine.statistics.success_rate == 100.0


def test_deterministic_ordering_and_duplicates(bulk_env: None, tmp_path: Path) -> None:
    image_ids = [_register_image(tmp_path / "source" / f"order-{index}.png") for index in range(3)]
    engine = _make_engine()

    result = engine.assign_tags([image_ids[2], image_ids[0], image_ids[0], image_ids[1]], tag_name="ordered")

    assert [item.entity_id for item in result.items] == [image_ids[0], image_ids[0], image_ids[1], image_ids[2]]
    assert result.items[1].status is BulkItemStatus.SKIPPED
    assert engine.statistics.duplicate_requests == 1


def test_empty_batch(bulk_env: None) -> None:
    engine = _make_engine()

    result = engine.delete_images([])

    assert result.items == []
    assert result.total == 0
    assert result.status == BulkBatchStatus.COMPLETED


def test_large_batch(bulk_env: None, tmp_path: Path) -> None:
    image_ids = [_register_image(tmp_path / "source" / f"large-{index}.png") for index in range(25)]
    collection = CollectionRepository().create_collection(name="Bulk Collection", kind=CollectionKind.STATIC)
    engine = _make_engine()

    result = engine.assign_collection(image_ids, collection_id=collection.collection_id)

    assert result.total == 25
    assert result.succeeded == 25
    assert engine.statistics.total_items == 25
    resolved_collection = CollectionRepository().get_collection(collection.collection_id)
    assert resolved_collection is not None
    assert resolved_collection.image_ids == set(image_ids)


def test_rename_and_organize_invocation(bulk_env: None, tmp_path: Path) -> None:
    image_path = tmp_path / "source" / "fate__saber.png"
    image_id = _register_image(image_path, series="Fate", characters=["Saber"], year=2004)
    engine = _make_engine()

    rename_result = engine.rename_images([image_id], rule=RenameRule(template="{series}_{character}_{index}"), dry_run=True)
    organize_result = engine.organize_images(
        [image_id],
        rules=[OrganizationRule(name="series", directory_template="{series}", priority=1, required_fields=("series",))],
        dry_run=True,
    )

    assert rename_result.dry_run is True
    assert rename_result.items[0].target_path is not None
    assert rename_result.items[0].target_path.name.startswith("Fate_Saber")
    assert organize_result.dry_run is True
    assert organize_result.items[0].target_path is not None
    assert "Fate" in organize_result.items[0].target_path.parts


def test_tag_assignment_and_removal(bulk_env: None, tmp_path: Path) -> None:
    first_id = _register_image(tmp_path / "source" / "tag-one.png")
    second_id = _register_image(tmp_path / "source" / "tag-two.png")
    engine = _make_engine()

    assigned = engine.assign_tags([first_id, second_id], tag_name="favorite", tag_category="state")
    removed = engine.remove_tags([first_id], tag_name="favorite")

    assert assigned.succeeded == 2
    assert removed.succeeded == 1
    repo = ImageRepository()
    first = repo.get_by_id(first_id)
    second = repo.get_by_id(second_id)
    assert first is not None and second is not None
    assert [tag.name for tag in first.tags] == []
    assert [tag.name for tag in second.tags] == ["favorite"]


def test_collection_assignment(bulk_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "source" / "collection.png")
    collection = CollectionRepository().create_collection(name="Set", kind=CollectionKind.STATIC)
    engine = _make_engine()

    result = engine.assign_collection([image_id], collection_id=collection.collection_id)

    assert result.succeeded == 1
    resolved = CollectionRepository().get_collection(collection.collection_id)
    assert resolved is not None
    assert resolved.image_ids == {image_id}


def test_review_approval_and_rejection(bulk_env: None, tmp_path: Path) -> None:
    review_repo = ReviewRepository()
    approve = review_repo.create_review_item(
        image_id=1,
        source_path=tmp_path / "review-a.png",
        operation_type="rename",
        confidence=0.8,
        proposed_value="A",
        current_value="B",
        series="Fate",
        character="Saber",
    )
    reject = review_repo.create_review_item(
        image_id=2,
        source_path=tmp_path / "review-b.png",
        operation_type="organize",
        confidence=0.2,
        proposed_value="C",
        current_value="D",
        series="Fate",
        character="Rin",
    )
    engine = _make_engine()

    approve_result = engine.approve_reviews([approve.review_id], reviewer="alice", reason="ok")
    reject_result = engine.reject_reviews([reject.review_id], reviewer="bob", reason="no")

    assert approve_result.succeeded == 1
    assert reject_result.succeeded == 1
    assert review_repo.get_review_item(approve.review_id).status.value == "approved"
    assert review_repo.get_review_item(reject.review_id).status.value == "rejected"
