from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.collections.collection_models import CollectionKind
from engine.config import settings
from engine.database.database import database_manager
from engine.database.models.embedding import Embedding
from engine.database.models.job import Job
from engine.database.models.metadata import MetadataRecord
from engine.database.models.review import Review
from engine.database.models.thumbnail import ThumbnailRecord
from engine.database.models.transaction import Transaction
from engine.database.models.image import image_character_association
from engine.library_integrity import IntegrityCheckName, IntegrityProgress, IntegritySeverity, LibraryIntegrityEngine, LibraryIntegrityService, LibraryIntegrityWorker
from engine.repositories.character_repository import CharacterRepository
from engine.repositories.collection_repository import CollectionRepository
from engine.repositories.dataset_repository import DatasetRepository
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.export_repository import ExportRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.job_repository import JobRepository
from engine.repositories.knowledge_repository import KnowledgeRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.review_repository import ReviewRepository
from engine.repositories.series_repository import SeriesRepository
from engine.repositories.tag_repository import TagRepository
from engine.repositories.thumbnail_repository import ThumbnailRepository


@pytest.fixture()
def integrity_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    ReviewRepository.reset_state()
    DatasetRepository._dataset_provenance = {}
    ExportRepository._manifest_store = {}
    ExportRepository._provenance_store = {}


def _register_image(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")
    repo = ImageRepository()
    image = repo.create_image(original_path=str(path), filename=path.name, extension=path.suffix)
    return image.id


def _add_complete_assets(image_id: int, image_path: Path) -> None:
    image_repo = ImageRepository()
    image = image_repo.get_by_id(image_id)
    assert image is not None

    metadata_repo = MetadataRepository()
    metadata_repo.create_metadata_record(image_id=image_id, mime_type="image/png", exif_data='{"Year": 2026}')

    embedding_repo = EmbeddingRepository()
    vector_path = image_path.parent / f"{image_path.stem}.npy"
    vector_path.write_bytes(b"vec")
    embedding_repo.create_embedding_record(image_id=image_id, vector_path=str(vector_path), model_name="mock", model_version="1")
    embedding_repo.commit()

    thumb_repo = ThumbnailRepository()
    thumb_path = image_path.parent / f"{image_path.stem}.webp"
    thumb_path.write_bytes(b"thumb")
    thumb_repo.create_thumbnail_record(
        image_id=image_id,
        size=256,
        format="webp",
        file_path=str(thumb_path),
        file_size_bytes=thumb_path.stat().st_size,
        cache_key=f"k-{image_id}",
        thumb_width=64,
        thumb_height=64,
    )

    tag_repo = TagRepository()
    tag = tag_repo.create_tag(name=f"tag-{image_id}", category="auto")
    tag_repo.assign_tag(image, tag)

    image.thumbnail_exists = True
    image.embedding_exists = True
    image_repo.commit()


def test_full_scan_healthy_library(integrity_env: None, tmp_path: Path) -> None:
    image_path = tmp_path / "library" / "healthy.png"
    image_id = _register_image(image_path)
    _add_complete_assets(image_id, image_path)
    KnowledgeRepository().create_version(version="1.0", description="snapshot")

    engine = LibraryIntegrityEngine()
    report = engine.run_full_scan()

    assert report.cancelled is False
    assert report.summary.checks_performed == 30
    assert IntegrityCheckName.MISSING_IMAGE_FILES in report.passed_checks
    assert report.summary.critical_errors == 0


def test_detect_missing_and_orphan_artifacts(integrity_env: None, tmp_path: Path) -> None:
    missing_path = tmp_path / "library" / "missing.png"
    image_id = _register_image(missing_path)
    missing_path.unlink()

    session = ImageRepository().session
    session.add(MetadataRecord(image_id=9999, mime_type="image/png"))
    session.add(Embedding(image_id=9998, vector_path=str(tmp_path / "ghost.npy"), model_name="m", model_version="1"))
    session.add(
        ThumbnailRecord(
            image_id=9997,
            size=256,
            format="webp",
            file_path=str(tmp_path / "ghost.webp"),
            file_size_bytes=1,
            cache_key="ghost",
            thumb_width=64,
            thumb_height=64,
        )
    )
    session.add(Review(image_id=9996, status="pending"))
    session.commit()

    report = LibraryIntegrityEngine().run_full_scan()

    assert any(item.check_name is IntegrityCheckName.MISSING_IMAGE_FILES for item in report.check_results)
    assert any(issue.image_id == image_id for issue in report.errors)
    assert any("orphan" in issue.suggested_repair.lower() or "missing image" in issue.description.lower() for issue in report.errors)


def test_detect_broken_references_and_duplicates(integrity_env: None, tmp_path: Path) -> None:
    image_path = tmp_path / "refs" / "ref.png"
    image_id = _register_image(image_path)
    _add_complete_assets(image_id, image_path)

    char_repo = CharacterRepository()
    series = SeriesRepository().create_series(name="Series")
    character = char_repo.create_character(name="Hero", series_id=series.id)

    session = ImageRepository().session
    session.execute(image_character_association.insert().values(image_id=image_id, character_id=character.id))
    session.execute(image_character_association.insert().values(image_id=123456, character_id=888888))

    duplicate_uuid = "00000000-0000-0000-0000-000000000042"
    session.query(Embedding).filter(Embedding.image_id == image_id).first().uuid = duplicate_uuid
    session.query(MetadataRecord).filter(MetadataRecord.image_id == image_id).first().uuid = duplicate_uuid
    session.commit()

    report = LibraryIntegrityEngine().run_database_scan()

    assert IntegrityCheckName.BROKEN_CHARACTER_REFERENCES in report.failed_checks
    assert IntegrityCheckName.DUPLICATE_UUID_DETECTION in report.failed_checks
    assert any(issue.severity is IntegritySeverity.CRITICAL for issue in report.errors)


def test_detect_invalid_paths_case_collisions_and_filenames(integrity_env: None, tmp_path: Path) -> None:
    first_id = _register_image(tmp_path / "Case" / "Image.PNG")
    second_id = _register_image(tmp_path / "case" / "image.png")
    third_id = _register_image(tmp_path / "misc" / "third.png")
    fourth_id = _register_image(tmp_path / "misc" / "fourth.png")

    repo = ImageRepository()
    first = repo.get_by_id(first_id)
    second = repo.get_by_id(second_id)
    third = repo.get_by_id(third_id)
    fourth = repo.get_by_id(fourth_id)
    assert first is not None and second is not None and third is not None and fourth is not None

    first.current_path = str(tmp_path / "Case" / "Image.PNG")
    second.current_path = str(tmp_path / "case" / "image.png")
    third.current_path = "relative/../bad\\path.png"
    fourth.current_path = str(tmp_path / "misc" / "CON.png")
    repo.commit()

    report = LibraryIntegrityEngine().run_filesystem_scan()

    assert IntegrityCheckName.INVALID_PATHS in report.failed_checks
    assert IntegrityCheckName.CASE_COLLISION_DETECTION in report.failed_checks
    assert IntegrityCheckName.RESERVED_FILENAME_DETECTION in report.failed_checks


def test_collection_pipeline_statistics_dataset_export_checks(integrity_env: None, tmp_path: Path) -> None:
    image_path = tmp_path / "mix" / "one.png"
    image_id = _register_image(image_path)

    collection_repo = CollectionRepository()
    root = collection_repo.create_collection(name="Root", kind=CollectionKind.STATIC)
    child = collection_repo.create_collection(name="Child", kind=CollectionKind.STATIC, parent_id=root.collection_id)
    child.parent_id = 999999

    _ = collection_repo.add_image(root.collection_id, 999999)

    job_repo = JobRepository()
    stuck_job = job_repo.create_job(job_type="scan")
    stuck_job.status = "running"
    stuck_job.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    bad_job = job_repo.create_job(job_type="scan")
    bad_job.status = "unknown"
    bad_job.progress = 101
    job_repo.commit()

    image_repo = ImageRepository()
    image = image_repo.get_by_id(image_id)
    assert image is not None
    image.thumbnail_exists = True
    image.embedding_exists = True
    image_repo.commit()

    dataset_repo = DatasetRepository()
    dataset_repo.save_dataset_provenance(999999, [str(tmp_path / "missing-source.png")])

    export_repo = ExportRepository()
    export_repo._manifest_store[("generic", image_id)] = {}
    export_repo._manifest_store[("unknown-format", image_id)] = {"file_path": str(tmp_path / "missing-export.txt")}

    report = LibraryIntegrityEngine().run_full_scan()

    assert IntegrityCheckName.COLLECTION_CONSISTENCY in report.failed_checks
    assert IntegrityCheckName.PIPELINE_CONSISTENCY in report.failed_checks
    assert IntegrityCheckName.STATISTICS_CONSISTENCY in report.failed_checks
    assert IntegrityCheckName.DATASET_CONSISTENCY in report.failed_checks
    assert IntegrityCheckName.EXPORT_CONSISTENCY in report.failed_checks


def test_service_modes_and_report_generation(integrity_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "service" / "scan.png")
    _ = image_id
    service = LibraryIntegrityService()

    quick = service.run_quick_scan()
    db_scan = service.run_database_scan()
    fs_scan = service.run_filesystem_scan()

    assert quick.summary.checks_performed < 30
    assert db_scan.summary.checks_performed < 30
    assert fs_scan.summary.checks_performed < 30
    assert quick.execution_time_seconds >= 0.0


def test_worker_cancellation_and_resume(integrity_env: None, tmp_path: Path) -> None:
    for index in range(3):
        image_id = _register_image(tmp_path / "worker" / f"{index}.png")
        _add_complete_assets(image_id, tmp_path / "worker" / f"{index}.png")

    cancelled_once = {"value": False}
    captured_scan_id = {"value": ""}

    def callback(event: object) -> None:
        if not isinstance(event, IntegrityProgress):
            return
        if event.current_check is None:
            return
        if cancelled_once["value"]:
            return
        cancelled_once["value"] = True
        captured_scan_id["value"] = event.scan_id
        service.cancel_scan(event.scan_id)

    engine = LibraryIntegrityEngine(callback=callback)
    service = LibraryIntegrityService(engine=engine)
    worker = LibraryIntegrityWorker(service=service)

    scan_id = worker.submit(mode="full")
    captured_scan_id["value"] = scan_id
    worker.start()
    worker._queue.join()

    cancelled_report = worker.result_for(scan_id)
    assert cancelled_report is not None
    assert cancelled_report.cancelled is True

    _ = worker.resume(scan_id)
    worker._queue.join()
    resumed_report = worker.result_for(scan_id)
    assert resumed_report is not None
    assert resumed_report.resumed is True

    worker.stop()
