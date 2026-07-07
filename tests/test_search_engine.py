"""Tests for the Semantic Search Engine (Commit 0015)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.embeddings import EmbeddingService
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import RecognitionService
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.image_repository import ImageRepository
from engine.search import (
    InMemorySearchBackend,
    SearchCheckpoint,
    SearchEngine,
    SearchIndex,
    SearchQueryError,
    SearchService,
)


@pytest.fixture()
def search_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    image = repo.create_image(
        original_path=str(path),
        filename=path.name,
        extension=path.suffix,
    )
    return image.id


def _build_search_ready_record(queue_manager: QueueManager, path: Path) -> int:
    image_id = _register_image(path)

    embedding_service = EmbeddingService(queue_manager=queue_manager)
    embedding_job = PipelineJob(source_path=str(path), queue_type=QueueType.EMBEDDING)
    embed_result = embedding_service.process_embedding_job(embedding_job)
    assert embed_result is not None

    recognition_service = RecognitionService(queue_manager=queue_manager)
    recognition_job = queue_manager.dequeue(QueueType.RECOGNITION)
    assert recognition_job is not None
    recognition_result = recognition_service.process_recognition_job(recognition_job)
    assert recognition_result is not None

    search_job = queue_manager.peek(QueueType.SEARCH)
    assert search_job is not None
    return image_id


def test_backend_upsert_and_query(search_env: None) -> None:
    backend = InMemorySearchBackend()
    from engine.search.search_models import SearchRecord

    backend.upsert(
        SearchRecord(
            image_id=1,
            path=Path("a.jpg"),
            vector=[1.0, 0.0],
            model_name="mock",
            model_version="1.0.0",
        )
    )
    backend.upsert(
        SearchRecord(
            image_id=2,
            path=Path("b.jpg"),
            vector=[0.0, 1.0],
            model_name="mock",
            model_version="1.0.0",
        )
    )

    result = backend.query(vector=[1.0, 0.0], top_k=2, min_similarity=0.0)

    assert len(result) == 2
    assert result[0].image_id == 1
    assert result[0].similarity == pytest.approx(1.0, rel=1e-6)


def test_engine_index_single_path(search_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    img_path = tmp_path / "bleach__rukia.jpg"
    img_path.write_bytes(b"fake")

    _build_search_ready_record(queue_manager, img_path)

    engine = SearchEngine()
    result = engine.index_path(img_path)

    assert result is not None
    assert result.path == img_path.resolve()
    assert engine.index.backend.size() == 1


def test_engine_checkpoint_skips_processed(search_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    img_path = tmp_path / "naruto__sakura.jpg"
    img_path.write_bytes(b"fake")

    _build_search_ready_record(queue_manager, img_path)

    engine = SearchEngine()
    checkpoint = SearchCheckpoint()
    checkpoint.add_processed(str(img_path.resolve()))

    result = engine.index_path(img_path, checkpoint=checkpoint)

    assert result is None


def test_engine_parallel_batch(search_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    paths: list[Path] = []
    for i in range(3):
        path = tmp_path / f"series__char_{i}.jpg"
        path.write_bytes(b"fake")
        _build_search_ready_record(queue_manager, path)
        paths.append(path)

    engine = SearchEngine(max_workers=2)
    results = engine.index_paths(paths)

    assert len(results) == 3
    assert engine.statistics.processed == 3
    assert engine.statistics.indexed == 3


def test_service_processes_search_job(search_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    img_path = tmp_path / "one_piece__luffy.jpg"
    img_path.write_bytes(b"fake")

    image_id = _build_search_ready_record(queue_manager, img_path)
    search_job = queue_manager.dequeue(QueueType.SEARCH)
    assert search_job is not None

    service = SearchService(queue_manager=queue_manager)
    result = service.process_search_job(search_job)

    assert result is not None
    assert result.image_id == image_id


def test_query_top_k_and_threshold(search_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    paths = [
        tmp_path / "fate__saber.jpg",
        tmp_path / "fate__rin.jpg",
        tmp_path / "bleach__ichigo.jpg",
    ]
    for path in paths:
        path.write_bytes(b"fake")
        _build_search_ready_record(queue_manager, path)

    engine = SearchEngine()
    engine.index_paths(paths)

    query_vector = engine._load_vector("synthetic-query")
    result = engine.search(query_vector=query_vector, top_k=2, min_similarity=0.1)

    assert len(result.matches) <= 2
    assert all(match.similarity >= 0.1 for match in result.matches)


def test_query_rejects_invalid_top_k(search_env: None) -> None:
    engine = SearchEngine(index=SearchIndex(backend=InMemorySearchBackend()))
    with pytest.raises(SearchQueryError):
        engine.search(query_vector=[0.1, 0.2], top_k=0)


def test_search_completed_event_emitted(search_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    img_path = tmp_path / "gundam__amuro.jpg"
    img_path.write_bytes(b"fake")
    _build_search_ready_record(queue_manager, img_path)

    events: list[object] = []

    def callback(event: object) -> None:
        events.append(event)

    engine = SearchEngine(callback=callback)
    engine.index_paths([img_path])

    assert any(type(event).__name__ == "SearchCompleted" for event in events)


def test_service_skips_job_without_source_path(search_env: None) -> None:
    queue_manager = QueueManager()
    service = SearchService(queue_manager=queue_manager)
    job = PipelineJob(queue_type=QueueType.SEARCH)

    result = service.process_search_job(job)

    assert result is None


def test_repository_can_read_embedding(search_env: None, tmp_path: Path) -> None:
    img_path = tmp_path / "repo__case.jpg"
    img_path.write_bytes(b"fake")
    image_id = _register_image(img_path)

    repo = EmbeddingRepository()
    repo.create_embedding_record(
        image_id=image_id,
        vector_path="cache/embeddings/mock/image_1.bin",
        model_name="mock",
        model_version="1.0.0",
    )
    repo.commit()

    from engine.repositories.search_repository import SearchRepository

    search_repo = SearchRepository()
    row = search_repo.get_embedding_by_path(str(img_path))

    assert row is not None
    assert row.image_id == image_id
