"""Tests for the Dataset Export Engine (Commit 0019)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.dataset import DatasetService
from engine.embeddings import EmbeddingService
from engine.export import ExportCheckpoint, ExportEngine, ExportFormatType, ExportOptions, ExportService
from engine.knowledge_graph import KnowledgeGraphService
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import RecognitionService
from engine.repositories.export_repository import ExportRepository
from engine.repositories.image_repository import ImageRepository
from engine.search import SearchService
from engine.tagging import TaggingService


@pytest.fixture()
def export_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    ExportRepository._manifest_store = {}
    ExportRepository._provenance_store = {}


def _register_image(path: Path) -> int:
    repo = ImageRepository()
    image = repo.create_image(original_path=str(path), filename=path.name, extension=path.suffix)
    return image.id


def _dequeue_search_job(queue_manager: QueueManager, *, expected_stage: str | None) -> PipelineJob:
    deferred: list[PipelineJob] = []
    selected: PipelineJob | None = None

    while True:
        job = queue_manager.dequeue(QueueType.SEARCH)
        assert job is not None
        stage = (job.metadata or {}).get("stage")
        if stage == expected_stage:
            selected = job
            break
        deferred.append(job)

    for job in deferred:
        queue_manager.enqueue(QueueType.SEARCH, job)

    assert selected is not None
    return selected


def _build_export_job(
    queue_manager: QueueManager,
    path: Path,
    *,
    keep_in_queue: bool = False,
    metadata: dict | None = None,
) -> PipelineJob:
    _register_image(path)

    embedding_service = EmbeddingService(queue_manager=queue_manager)
    embedding_job = PipelineJob(source_path=str(path), queue_type=QueueType.EMBEDDING)
    assert embedding_service.process_embedding_job(embedding_job) is not None

    recognition_service = RecognitionService(queue_manager=queue_manager)
    recognition_job = queue_manager.dequeue(QueueType.RECOGNITION)
    assert recognition_job is not None
    assert recognition_service.process_recognition_job(recognition_job) is not None

    search_service = SearchService(queue_manager=queue_manager)
    search_job = _dequeue_search_job(queue_manager, expected_stage=None)
    assert search_service.process_search_job(search_job) is not None

    kg_job = _dequeue_search_job(queue_manager, expected_stage="knowledge_graph")
    kg_service = KnowledgeGraphService(queue_manager=queue_manager)
    assert kg_service.process_knowledge_graph_job(kg_job) is not None

    tagging_job = _dequeue_search_job(queue_manager, expected_stage="tagging")
    tagging_service = TaggingService(queue_manager=queue_manager)
    assert tagging_service.process_tagging_job(tagging_job) is not None

    dataset_job = _dequeue_search_job(queue_manager, expected_stage="dataset")
    assert dataset_job.metadata.get("stage") == "dataset"
    if metadata:
        dataset_job.metadata.update(metadata)

    dataset_service = DatasetService(queue_manager=queue_manager)
    assert dataset_service.process_dataset_job(dataset_job) is not None

    if keep_in_queue:
        export_job = _dequeue_search_job(queue_manager, expected_stage="export")
        queue_manager.enqueue(QueueType.SEARCH, export_job)
    else:
        export_job = _dequeue_search_job(queue_manager, expected_stage="export")
    assert export_job.metadata.get("stage") == "export"
    return export_job


def test_generic_export(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "generic__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path)

    service = ExportService(queue_manager=queue_manager)
    result = service.process_export_job(job)

    assert result is not None
    assert result.format_type == ExportFormatType.GENERIC


def test_flux_export(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "flux__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path, metadata={"export_format": "flux"})

    service = ExportService(queue_manager=queue_manager)
    result = service.process_export_job(job)

    assert result is not None
    assert result.format_type == ExportFormatType.FLUX


def test_sdxl_export(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "sdxl__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path, metadata={"export_format": "sdxl"})

    service = ExportService(queue_manager=queue_manager)
    result = service.process_export_job(job)

    assert result is not None
    assert result.format_type == ExportFormatType.SDXL


def test_stable_diffusion_export(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "sd__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path, metadata={"export_format": "stable_diffusion"})

    service = ExportService(queue_manager=queue_manager)
    result = service.process_export_job(job)

    assert result is not None
    assert result.format_type == ExportFormatType.STABLE_DIFFUSION


def test_comfyui_export(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "comfy__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path, metadata={"export_format": "comfyui"})

    service = ExportService(queue_manager=queue_manager)
    result = service.process_export_job(job)

    assert result is not None
    assert result.format_type == ExportFormatType.COMFYUI


def test_batch_export(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    jobs: list[PipelineJob] = []
    for i in range(3):
        path = tmp_path / f"batch__{i}.jpg"
        path.write_bytes(b"fake")
        jobs.append(_build_export_job(queue_manager, path))

    service = ExportService(queue_manager=queue_manager)
    results = service.process_export_jobs(jobs)

    assert len(results) == 3


def test_dry_run_mode(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "dryrun__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path, metadata={"dry_run": True})

    service = ExportService(queue_manager=queue_manager)
    result = service.process_export_job(job)

    assert result is not None
    assert result.dry_run is True

    repo = ExportRepository()
    manifest = repo.get_export_manifest(format_type=ExportFormatType.GENERIC, image_id=result.image_id)
    assert manifest == {}


def test_incremental_export(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "incremental__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path)

    service = ExportService(queue_manager=queue_manager)
    first = service.process_export_job(job)
    second = service.process_export_job(job)

    assert first is not None
    assert second is None


def test_resume_after_interruption(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    jobs: list[PipelineJob] = []
    for i in range(4):
        path = tmp_path / f"resume__{i}.jpg"
        path.write_bytes(b"fake")
        jobs.append(_build_export_job(queue_manager, path))

    checkpoint = ExportCheckpoint()
    checkpoint.add_processed(jobs[0].source_path or "", format_type=ExportFormatType.GENERIC)

    service = ExportService(queue_manager=queue_manager)
    results = service.process_export_jobs(jobs, checkpoint=checkpoint)

    assert len(results) == 3


def test_checkpoint_recovery(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "checkpoint__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path)

    checkpoint = ExportCheckpoint()
    checkpoint.add_processed(job.source_path or "", format_type=ExportFormatType.GENERIC)

    service = ExportService(queue_manager=queue_manager)
    result = service.process_export_job(job, checkpoint=checkpoint)

    assert result is None


def test_duplicate_prevention(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "duplicate__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path)

    service = ExportService(queue_manager=queue_manager)
    first = service.process_export_job(job)
    second = service.process_export_job(job)

    assert first is not None
    assert second is None

    repo = ExportRepository()
    assert repo.count_exports(format_type=ExportFormatType.GENERIC) == 1


def test_repository_persistence(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "repo__persist.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path, metadata={"export_format": "flux"})

    service = ExportService(queue_manager=queue_manager)
    result = service.process_export_job(job)

    assert result is not None

    repo = ExportRepository()
    manifest = repo.get_export_manifest(format_type=ExportFormatType.FLUX, image_id=result.image_id)
    provenance = repo.get_export_provenance(format_type=ExportFormatType.FLUX, image_id=result.image_id)
    assert manifest != {}
    assert len(provenance) > 0


def test_thread_safety(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    paths: list[Path] = []
    for i in range(6):
        path = tmp_path / f"threadsafe__{i}.jpg"
        path.write_bytes(b"fake")
        _ = _build_export_job(queue_manager, path)
        paths.append(path)

    engine = ExportEngine(max_workers=4)
    options = ExportOptions(format_type=ExportFormatType.GENERIC)
    results = engine.export_paths(paths, options=options)

    assert len(results) == 6


def test_event_emission(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "events__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path)

    events: list[object] = []

    def callback(event: object) -> None:
        events.append(event)

    engine = ExportEngine(callback=callback)
    options = ExportOptions.from_metadata(job.metadata)
    _ = engine.export_paths([path], options=options, semantic=job.metadata)

    assert any(type(e).__name__ == "ExportCompleted" for e in events)


def test_statistics(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "stats__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path)

    engine = ExportEngine()
    options = ExportOptions.from_metadata(job.metadata)
    _ = engine.export_paths([path], options=options, semantic=job.metadata)

    assert engine.statistics.processed >= 1
    assert engine.statistics.exported >= 1


def test_pipeline_integration(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "pipeline__sample.jpg"
    path.write_bytes(b"fake")
    _ = _build_export_job(queue_manager, path, keep_in_queue=True)

    export_job = queue_manager.peek(QueueType.SEARCH)
    assert export_job is not None
    assert export_job.metadata.get("stage") == "export"


def test_rebuild_mode(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "rebuild__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_export_job(queue_manager, path)

    service = ExportService(queue_manager=queue_manager)
    first = service.process_export_job(job)
    assert first is not None

    rebuild_job = PipelineJob(
        source_path=job.source_path,
        queue_type=QueueType.SEARCH,
        metadata={**(job.metadata or {}), "overwrite": True},
    )
    rebuilt = service.process_export_job(rebuild_job)

    assert rebuilt is not None
    assert rebuilt.rebuilt is True


def test_idempotency(export_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "idempotent__sample.jpg"
    path.write_bytes(b"fake")
    _ = _build_export_job(queue_manager, path)

    engine = ExportEngine()
    options = ExportOptions(format_type=ExportFormatType.GENERIC)
    first = engine.export_path(path, options=options)
    second = engine.export_path(path, options=options)

    assert first is not None
    assert second is None
