"""Tests for the Dataset Engine (Commit 0018)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.dataset import DatasetCheckpoint, DatasetEngine, DatasetService
from engine.embeddings import EmbeddingService
from engine.knowledge_graph import KnowledgeGraphService
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import RecognitionService
from engine.repositories.dataset_repository import DatasetRepository
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.hash_repository import HashRepository
from engine.repositories.image_repository import ImageRepository
from engine.search import SearchService
from engine.tagging import TaggingService


@pytest.fixture()
def dataset_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _register_image(path: Path) -> int:
    repo = ImageRepository()
    image = repo.create_image(original_path=str(path), filename=path.name, extension=path.suffix)
    return image.id


def _build_dataset_job(
    queue_manager: QueueManager,
    path: Path,
    *,
    keep_in_queue: bool = False,
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
    search_job = queue_manager.dequeue(QueueType.SEARCH)
    assert search_job is not None
    assert search_service.process_search_job(search_job) is not None

    kg_job = queue_manager.dequeue(QueueType.SEARCH)
    assert kg_job is not None
    kg_service = KnowledgeGraphService(queue_manager=queue_manager)
    assert kg_service.process_knowledge_graph_job(kg_job) is not None

    tagging_job = queue_manager.dequeue(QueueType.SEARCH)
    assert tagging_job is not None
    tagging_service = TaggingService(queue_manager=queue_manager)
    assert tagging_service.process_tagging_job(tagging_job) is not None

    if keep_in_queue:
        dataset_job = queue_manager.peek(QueueType.SEARCH)
    else:
        dataset_job = queue_manager.dequeue(QueueType.SEARCH)
    assert dataset_job is not None
    assert dataset_job.metadata.get("stage") == "dataset"
    return dataset_job


def test_dataset_building(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "fate__saber.jpg"
    path.write_bytes(b"fake")

    job = _build_dataset_job(queue_manager, path)
    service = DatasetService(queue_manager=queue_manager)
    result = service.process_dataset_job(job)

    assert result is not None
    assert result.entry.payload["image"]["filename"] == path.name


def test_confidence_scoring(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "one_piece__luffy.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    engine = DatasetEngine()
    result = engine.build_path(path, semantic=job.metadata)

    assert result is not None
    assert 0.0 <= result.entry.confidence_score <= 1.0


def test_quality_scoring(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "quality__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    engine = DatasetEngine()
    result = engine.build_path(path, semantic=job.metadata)

    assert result is not None
    assert 0.0 <= result.entry.quality_score <= 1.0


def test_completeness_scoring(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "complete__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    engine = DatasetEngine()
    result = engine.build_path(path, semantic=job.metadata)

    assert result is not None
    assert 0.0 <= result.entry.completeness_score <= 1.0


def test_batch_generation(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    paths = []
    for i in range(3):
        path = tmp_path / f"batch__{i}.jpg"
        path.write_bytes(b"fake")
        _build_dataset_job(queue_manager, path)
        paths.append(path)

    engine = DatasetEngine(max_workers=2)
    results = engine.build_paths(paths)

    assert len(results) == 3


def test_incremental_generation_skips_existing(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "incremental__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    service = DatasetService(queue_manager=queue_manager)
    first = service.process_dataset_job(job)
    second = service.process_dataset_job(job)

    assert first is not None
    assert second is None


def test_checkpoint_recovery(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "checkpoint__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    checkpoint = DatasetCheckpoint()
    checkpoint.add_processed(str(path.resolve()))
    service = DatasetService(queue_manager=queue_manager)
    result = service.process_dataset_job(job, checkpoint=checkpoint)

    assert result is None


def test_duplicate_prevention(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    p1 = tmp_path / "dup_a.jpg"
    p2 = tmp_path / "dup_b.jpg"
    p1.write_bytes(b"x")
    p2.write_bytes(b"x")
    id1 = _register_image(p1)
    id2 = _register_image(p2)

    dup_repo = DuplicateRepository()
    dup_repo.create_duplicate(
        image_a_id=min(id1, id2),
        image_b_id=max(id1, id2),
        match_type="exact",
        confidence="high",
        sha256_match=True,
        phash_distance=0,
        ahash_distance=0,
        dhash_distance=0,
        overall_score=1.0,
    )

    job = _build_dataset_job(queue_manager, p1)
    service = DatasetService(queue_manager=queue_manager)
    result = service.process_dataset_job(job)

    assert result is not None
    assert len(result.entry.payload["duplicates"]) >= 1


def test_parallel_workers(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    jobs = []
    for i in range(4):
        path = tmp_path / f"parallel__{i}.jpg"
        path.write_bytes(b"fake")
        jobs.append(_build_dataset_job(queue_manager, path))

    service = DatasetService(queue_manager=queue_manager)
    results = service.process_dataset_jobs(jobs)

    assert len(results) == 4


def test_repository_persistence(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "repo__persist.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    engine = DatasetEngine()
    result = engine.build_path(path, semantic=job.metadata)
    assert result is not None

    repo = DatasetRepository()
    provenance = repo.get_dataset_provenance(result.image_id)
    assert len(provenance) > 0


def test_events(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "events__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    events: list[object] = []

    def callback(event: object) -> None:
        events.append(event)

    engine = DatasetEngine(callback=callback)
    _ = engine.build_paths([path], semantic=job.metadata)

    assert any(type(e).__name__ == "DatasetCompleted" for e in events)


def test_statistics(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "stats__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    engine = DatasetEngine()
    _ = engine.build_paths([path], semantic=job.metadata)

    assert engine.statistics.processed >= 1


def test_thread_safety(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    paths = []
    for i in range(6):
        path = tmp_path / f"threadsafe__{i}.jpg"
        path.write_bytes(b"fake")
        _build_dataset_job(queue_manager, path)
        paths.append(path)

    engine = DatasetEngine(max_workers=4)
    results = engine.build_paths(paths)

    assert len(results) == 6


def test_pipeline_integration_from_tagging(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "pipeline__sample.jpg"
    path.write_bytes(b"fake")
    _ = _build_dataset_job(queue_manager, path, keep_in_queue=True)

    dataset_job = queue_manager.peek(QueueType.SEARCH)
    assert dataset_job is not None
    assert dataset_job.metadata.get("stage") == "dataset"


def test_rebuild_mode(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "rebuild__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    service = DatasetService(queue_manager=queue_manager)
    first = service.process_dataset_job(job)
    assert first is not None

    rebuilt = service.process_dataset_job(job, rebuild=True)
    assert rebuilt is not None
    assert rebuilt.rebuilt is True


def test_idempotency(dataset_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "idempotent__sample.jpg"
    path.write_bytes(b"fake")
    job = _build_dataset_job(queue_manager, path)

    engine = DatasetEngine()
    first = engine.build_path(path, semantic=job.metadata)
    second = engine.build_path(path, semantic=job.metadata)

    assert first is not None
    assert second is None
