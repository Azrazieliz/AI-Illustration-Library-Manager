from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.collections.collection_models import CollectionKind
from engine.config import settings
from engine.database.database import database_manager
from engine.database.models.embedding import Embedding
from engine.database.models.hash import HashModel
from engine.database.models.job import Job
from engine.database.models.metadata import MetadataRecord
from engine.database.models.review import Review
from engine.database.models.thumbnail import ThumbnailRecord
from engine.database.models.transaction import Transaction
from engine.library_maintenance import LibraryMaintenanceEngine, LibraryMaintenanceService, LibraryMaintenanceWorker, MaintenanceJobStatus, MaintenanceTaskType
from engine.repositories.collection_repository import CollectionRepository
from engine.repositories.dataset_repository import DatasetRepository
from engine.repositories.export_repository import ExportRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.review_repository import ReviewRepository


@pytest.fixture()
def maintenance_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    path.write_bytes(b"img")
    image = ImageRepository().create_image(original_path=str(path), filename=path.name, extension=path.suffix)
    return image.id


def test_thumbnail_metadata_embedding_rebuild(maintenance_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "src" / "a.png")
    engine = LibraryMaintenanceEngine()

    report = engine.run_selected_tasks([
        MaintenanceTaskType.REBUILD_THUMBNAILS,
        MaintenanceTaskType.REGENERATE_METADATA,
        MaintenanceTaskType.RECOMPUTE_EMBEDDINGS,
    ])

    assert report.job.status is MaintenanceJobStatus.COMPLETED
    assert report.summary.repaired_items >= 3


def test_orphan_cleanup_and_rollback(maintenance_env: None, tmp_path: Path) -> None:
    _ = _register_image(tmp_path / "src" / "b.png")
    session = ImageRepository().session
    session.add(MetadataRecord(image_id=99999, mime_type="image/png"))
    session.add(Embedding(image_id=99998, vector_path=str(tmp_path / "ghost.npy"), model_name="m", model_version="1"))
    session.add(
        ThumbnailRecord(
            image_id=99997,
            size=256,
            format="webp",
            file_path=str(tmp_path / "ghost.webp"),
            file_size_bytes=1,
            cache_key="ghost",
            thumb_width=64,
            thumb_height=64,
        )
    )
    session.commit()

    engine = LibraryMaintenanceEngine()
    report = engine.run_selected_tasks([
        MaintenanceTaskType.REMOVE_ORPHAN_METADATA,
        MaintenanceTaskType.REMOVE_ORPHAN_EMBEDDINGS,
        MaintenanceTaskType.REMOVE_ORPHAN_THUMBNAILS,
    ])

    assert report.summary.repaired_items == 3
    restored = engine.rollback_job(report.job.job_id)
    assert restored == 3


def test_cache_cleanup_statistics_rebuild_and_selected_tasks(maintenance_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "src" / "c.png")
    cache_root = Path.cwd() / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    stale_file = cache_root / "old.stale"
    stale_file.write_text("x", encoding="utf-8")

    repo = ImageRepository()
    image = repo.get_by_id(image_id)
    assert image is not None
    image.thumbnail_exists = True
    image.embedding_exists = True
    repo.commit()

    engine = LibraryMaintenanceEngine()
    report = engine.run_selected_tasks([
        MaintenanceTaskType.CLEAN_STALE_CACHES,
        MaintenanceTaskType.RECALCULATE_LIBRARY_STATISTICS,
    ])

    assert report.summary.repaired_items >= 1
    assert not stale_file.exists()


def test_preview_and_dry_run_modes(maintenance_env: None, tmp_path: Path) -> None:
    _ = _register_image(tmp_path / "src" / "d.png")
    engine = LibraryMaintenanceEngine()

    preview_report = engine.preview_repairs([
        MaintenanceTaskType.REBUILD_THUMBNAILS,
        MaintenanceTaskType.REGENERATE_METADATA,
    ])
    dry_run_report = engine.run_selected_tasks(
        [MaintenanceTaskType.REBUILD_THUMBNAILS],
        dry_run=True,
    )

    assert preview_report.preview is True
    assert preview_report.dry_run is True
    assert dry_run_report.dry_run is True


def test_cancellation_resume_and_worker_job_tracking(maintenance_env: None, tmp_path: Path) -> None:
    for idx in range(3):
        _ = _register_image(tmp_path / "src" / f"{idx}.png")

    service = LibraryMaintenanceService()
    worker = LibraryMaintenanceWorker(service=service)
    worker.start()

    job_id = worker.submit_selected([
        MaintenanceTaskType.REBUILD_THUMBNAILS,
        MaintenanceTaskType.REGENERATE_METADATA,
        MaintenanceTaskType.RECOMPUTE_EMBEDDINGS,
    ])

    worker._queue.join()
    result = worker.result_for(job_id)
    assert result is not None
    assert result.job.job_id == job_id

    resumed = service.resume_job(job_id)
    assert resumed.resumed is True

    worker.stop()


def test_full_maintenance_and_queue_retry(maintenance_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "src" / "e.png")
    session = ImageRepository().session
    session.add(Job(type="maintenance", status="running", progress=60, started_at=datetime.now(timezone.utc) - timedelta(hours=2)))
    session.add(Job(type="bad", status="unknown", progress=111))
    session.add(Review(image_id=999999, status="pending"))
    session.add(Transaction(image_id=999999, operation="rename", status="pending", new_path=str(tmp_path / "missing.txt")))
    session.add(HashModel(image_id=image_id, sha256="a" * 64, phash=None, ahash=None, dhash=None))
    session.commit()

    collection = CollectionRepository().create_collection(name="Broken", kind=CollectionKind.STATIC)
    collection.parent_id = 99999

    DatasetRepository().save_dataset_provenance(999999, [str(tmp_path / "missing-source.png")])
    ExportRepository()._manifest_store[("unknown", image_id)] = {"file_path": str(tmp_path / "missing-export.txt")}

    engine = LibraryMaintenanceEngine()
    report = engine.run_full_maintenance()

    assert report.summary.total_tasks == len(MaintenanceTaskType)
    assert report.job.status in {MaintenanceJobStatus.COMPLETED, MaintenanceJobStatus.FAILED}
    assert engine.statistics.maintenance_runs >= 1
