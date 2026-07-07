from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.collections import CollectionKind
from engine.config import settings
from engine.database.database import database_manager
from engine.database.models.duplicate import DuplicateRecord
from engine.database.models.embedding import Embedding
from engine.database.models.hash import HashModel
from engine.database.models.metadata import MetadataRecord
from engine.database.models.thumbnail import ThumbnailRecord
from engine.library import LibraryHealthStatus, LibraryService, RecommendationSeverity
from engine.repositories.character_repository import CharacterRepository
from engine.repositories.collection_repository import CollectionRepository
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.series_repository import SeriesRepository
from engine.repositories.tag_repository import TagRepository


@pytest.fixture()
def library_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    CollectionRepository.reset_state()


def _create_image(path: Path, *, scanned_at: datetime) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"img")
    repo = ImageRepository()
    image = repo.create_image(original_path=str(path), filename=path.name, extension=path.suffix)
    repo.update_image(image, scan_date=scanned_at, filesize=path.stat().st_size)
    return image.id


def test_library_summary_and_health_analysis(library_env: None, tmp_path: Path) -> None:
    existing_path = tmp_path / "library" / "existing.png"
    missing_path = tmp_path / "library" / "missing.png"

    scanned = datetime(2026, 7, 7, 9, 30, tzinfo=timezone.utc)
    existing_id = _create_image(existing_path, scanned_at=scanned)

    image_repo = ImageRepository()
    missing_image = image_repo.create_image(original_path=str(missing_path), filename=missing_path.name, extension=missing_path.suffix)
    image_repo.update_image(missing_image, scan_date=scanned, filesize=1024)

    collection_repo = CollectionRepository()
    root = collection_repo.create_collection(name="Root", kind=CollectionKind.STATIC)
    empty = collection_repo.create_collection(name="Empty", kind=CollectionKind.STATIC)
    _ = empty
    _ = collection_repo.add_image(root.collection_id, existing_id)
    _ = collection_repo.add_image(root.collection_id, 999999)

    duplicate_repo = DuplicateRepository()
    _ = duplicate_repo.create_duplicate(
        image_a_id=existing_id,
        image_b_id=missing_image.id,
        match_type="exact",
        confidence="high",
        sha256_match=True,
        phash_distance=None,
        ahash_distance=None,
        dhash_distance=None,
        overall_score=1.0,
        status="pending",
    )

    session = image_repo.session
    session.add(
        HashModel(image_id=777777, sha256="a" * 64, phash=None, ahash=None, dhash=None)
    )
    session.add(
        MetadataRecord(image_id=777778, mime_type="image/png")
    )
    session.add(
        Embedding(image_id=777779, vector_path="cache/embeddings/orphan.npy", model_name="mock", model_version="1")
    )
    session.add(
        ThumbnailRecord(
            image_id=777780,
            size=256,
            format="webp",
            file_path="cache/thumbnails/orphan.webp",
            file_size_bytes=10,
            cache_key="orphan",
            thumb_width=64,
            thumb_height=64,
        )
    )
    session.add(
        DuplicateRecord(
            image_a_id=777781,
            image_b_id=777782,
            match_type="exact",
            confidence="high",
            sha256_match=False,
            phash_distance=None,
            ahash_distance=None,
            dhash_distance=None,
            overall_score=0.2,
            status="pending",
        )
    )
    session.commit()

    service = LibraryService()
    summary = service.summary()
    health = service.health()
    analysis = service.analyze()

    assert summary.total_images == 2
    assert summary.total_collections == 2
    assert summary.missing_files == 1
    assert summary.broken_references == 1
    assert summary.orphan_records >= 5
    assert summary.empty_collections == 1
    assert summary.duplicate_pairs >= 1
    assert summary.last_scan_at is not None

    assert health.status in (LibraryHealthStatus.WARNING, LibraryHealthStatus.CRITICAL)
    assert health.score < 100.0

    recommendation_codes = {item.code for item in analysis.cleanup_recommendations}
    assert "restore-missing-files" in recommendation_codes
    assert "repair-broken-references" in recommendation_codes
    assert "cleanup-orphan-records" in recommendation_codes
    assert "review-empty-collections" in recommendation_codes
    assert "resolve-duplicates" in recommendation_codes


def test_library_statistics_for_duplicates_and_taxonomy(library_env: None, tmp_path: Path) -> None:
    path_a = tmp_path / "taxonomy" / "a.png"
    path_b = tmp_path / "taxonomy" / "b.png"
    path_c = tmp_path / "taxonomy" / "c.png"

    scanned_day = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)
    id_a = _create_image(path_a, scanned_at=scanned_day)
    id_b = _create_image(path_b, scanned_at=scanned_day)
    id_c = _create_image(path_c, scanned_at=scanned_day)

    image_repo = ImageRepository()
    image_a = image_repo.get_image(id_a)
    image_b = image_repo.get_image(id_b)
    assert image_a is not None
    assert image_b is not None

    tag_repo = TagRepository()
    tag = tag_repo.create_tag(name="landscape", category="style")
    _ = tag_repo.assign_tag(image_a, tag)
    _ = tag_repo.assign_tag(image_b, tag)

    series_repo = SeriesRepository()
    series = series_repo.create_series(name="Series One")

    character_repo = CharacterRepository()
    character = character_repo.create_character(name="Hero", series_id=series.id)

    image_a.series_id = series.id
    image_b.series_id = series.id
    image_a.characters.append(character)
    image_b.characters.append(character)
    image_repo.commit()

    duplicate_repo = DuplicateRepository()
    _ = duplicate_repo.create_duplicate(
        image_a_id=id_a,
        image_b_id=id_b,
        match_type="exact",
        confidence="high",
        sha256_match=True,
        phash_distance=None,
        ahash_distance=None,
        dhash_distance=None,
        overall_score=1.0,
        status="pending",
    )

    stored = duplicate_repo.get_canonical(id_a, id_b)
    assert stored is not None
    _ = duplicate_repo.mark_reviewed(stored)

    _ = duplicate_repo.create_duplicate(
        image_a_id=id_a,
        image_b_id=id_c,
        match_type="perceptual",
        confidence="medium",
        sha256_match=False,
        phash_distance=4,
        ahash_distance=3,
        dhash_distance=5,
        overall_score=0.65,
        status="rejected",
    )

    service = LibraryService()
    statistics = service.statistics()

    assert statistics.duplicate_statistics.total_pairs == 2
    assert statistics.duplicate_statistics.reviewed == 1
    assert statistics.duplicate_statistics.rejected == 1
    assert statistics.duplicate_statistics.exact == 1
    assert statistics.duplicate_statistics.perceptual == 1

    assert len(statistics.tag_statistics) >= 1
    assert statistics.tag_statistics[0].name == "landscape"
    assert statistics.tag_statistics[0].image_count == 2

    assert len(statistics.character_statistics) >= 1
    assert statistics.character_statistics[0].name == "Hero"
    assert statistics.character_statistics[0].image_count == 2

    assert len(statistics.series_statistics) >= 1
    assert statistics.series_statistics[0].name == "Series One"
    assert statistics.series_statistics[0].image_count == 2


def test_library_storage_folder_scan_history_and_analysis_lists(library_env: None, tmp_path: Path) -> None:
    root_a = tmp_path / "f1"
    root_b = tmp_path / "f2"

    day_one = datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)
    day_two = datetime(2026, 7, 6, 8, 0, tzinfo=timezone.utc)

    _ = _create_image(root_a / "a.png", scanned_at=day_one)
    _ = _create_image(root_a / "b.png", scanned_at=day_two)
    _ = _create_image(root_b / "c.png", scanned_at=day_two)

    service = LibraryService()
    statistics = service.statistics()
    analysis = service.analyze()

    assert statistics.storage_statistics is not None
    assert statistics.storage_statistics.total_bytes > 0
    assert statistics.storage_statistics.average_bytes > 0
    assert statistics.storage_statistics.largest_bytes > 0

    folder_paths = {item.folder_path for item in statistics.folder_statistics}
    assert str(root_a) in folder_paths
    assert str(root_b) in folder_paths

    assert len(statistics.scan_history) == 2
    assert statistics.scan_history[0].images_scanned >= statistics.scan_history[1].images_scanned

    assert isinstance(analysis.missing_files, list)
    assert isinstance(analysis.broken_references, list)
    assert isinstance(analysis.orphan_records, list)
    assert isinstance(analysis.empty_collections, list)

    severities = {item.severity for item in analysis.cleanup_recommendations}
    assert all(isinstance(level, RecommendationSeverity) for level in severities)
