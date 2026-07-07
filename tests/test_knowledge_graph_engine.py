"""Tests for the Knowledge Graph Engine (Commit 0016)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.embeddings import EmbeddingService
from engine.knowledge_graph import EdgeType, KnowledgeGraphCheckpoint, KnowledgeGraphEngine, KnowledgeGraphService
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import RecognitionService
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.tag_repository import TagRepository
from engine.search import SearchService


@pytest.fixture()
def kg_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _queue_to_kg_job(queue_manager: QueueManager, path: Path, artist: str | None = None) -> PipelineJob:
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
    if artist:
        search_job.metadata["artist"] = artist
    assert search_service.process_search_job(search_job) is not None

    kg_job = queue_manager.dequeue(QueueType.SEARCH)
    assert kg_job is not None
    assert (kg_job.metadata or {}).get("stage") == "knowledge_graph"
    return kg_job


def test_service_processes_knowledge_graph_job(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "fate__saber.jpg"
    image_path.write_bytes(b"fake")

    kg_job = _queue_to_kg_job(queue_manager, image_path, artist="Takeuchi")

    service = KnowledgeGraphService(queue_manager=queue_manager)
    result = service.process_knowledge_graph_job(kg_job)

    assert result is not None
    assert result.created_nodes > 0
    assert result.created_edges > 0


def test_checkpoint_skips_processed_path(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "bleach__ichigo.jpg"
    image_path.write_bytes(b"fake")

    kg_job = _queue_to_kg_job(queue_manager, image_path)

    service = KnowledgeGraphService(queue_manager=queue_manager)
    checkpoint = KnowledgeGraphCheckpoint()
    checkpoint.add_processed(str(image_path.resolve()))

    result = service.process_knowledge_graph_job(kg_job, checkpoint=checkpoint)

    assert result is None


def test_parallel_processing_multiple_paths(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    jobs: list[PipelineJob] = []
    for index in range(3):
        image_path = tmp_path / f"series__character_{index}.jpg"
        image_path.write_bytes(b"fake")
        jobs.append(_queue_to_kg_job(queue_manager, image_path, artist="ArtistA"))

    service = KnowledgeGraphService(queue_manager=queue_manager)
    results = service.process_knowledge_graph_jobs(jobs)

    assert len(results) == 3


def test_neighbor_lookup(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "naruto__sasuke.jpg"
    image_path.write_bytes(b"fake")
    kg_job = _queue_to_kg_job(queue_manager, image_path)

    service = KnowledgeGraphService(queue_manager=queue_manager)
    result = service.process_knowledge_graph_job(kg_job)
    assert result is not None

    image_node_id = f"image:{result.image_id}"
    neighbors = service.neighbors(image_node_id)

    assert len(neighbors) > 0


def test_shortest_path_query(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()

    path_a = tmp_path / "one_piece__luffy.jpg"
    path_b = tmp_path / "one_piece__zoro.jpg"
    path_a.write_bytes(b"fake")
    path_b.write_bytes(b"fake")

    job_a = _queue_to_kg_job(queue_manager, path_a)
    job_b = _queue_to_kg_job(queue_manager, path_b)

    service = KnowledgeGraphService(queue_manager=queue_manager)
    res_a = service.process_knowledge_graph_job(job_a)
    res_b = service.process_knowledge_graph_job(job_b)
    assert res_a is not None and res_b is not None

    image_node_a = f"image:{res_a.image_id}"
    image_node_b = f"image:{res_b.image_id}"
    path = service.shortest_path(image_node_a, image_node_b)

    assert path is not None
    assert path.edge_count >= 2


def test_traversal_query(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "eva__asuka.jpg"
    image_path.write_bytes(b"fake")

    kg_job = _queue_to_kg_job(queue_manager, image_path)
    service = KnowledgeGraphService(queue_manager=queue_manager)
    result = service.process_knowledge_graph_job(kg_job)
    assert result is not None

    traversal = service.traverse(start_node_id=f"image:{result.image_id}", max_depth=2)

    assert len(traversal.visited_node_ids) > 1


def test_duplicate_group_nodes_and_edges(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()

    path_a = tmp_path / "dup__a.jpg"
    path_b = tmp_path / "dup__b.jpg"
    path_a.write_bytes(b"a")
    path_b.write_bytes(b"a")

    id_a = _register_image(path_a)
    id_b = _register_image(path_b)

    dup_repo = DuplicateRepository()
    dup_repo.create_duplicate(
        image_a_id=min(id_a, id_b),
        image_b_id=max(id_a, id_b),
        match_type="exact",
        confidence="high",
        sha256_match=True,
        phash_distance=0,
        ahash_distance=0,
        dhash_distance=0,
        overall_score=1.0,
    )

    kg_job_a = _queue_to_kg_job(queue_manager, path_a)
    service = KnowledgeGraphService(queue_manager=queue_manager)
    result = service.process_knowledge_graph_job(kg_job_a)
    assert result is not None

    neighbors = service.neighbors(f"image:{result.image_id}", edge_type=EdgeType.IN_DUPLICATE_GROUP)
    assert len(neighbors) >= 1


def test_merge_duplicate_nodes_for_artist(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()

    path_a = tmp_path / "fate__rin.jpg"
    path_b = tmp_path / "fate__sakura.jpg"
    path_a.write_bytes(b"fake")
    path_b.write_bytes(b"fake")

    job_a = _queue_to_kg_job(queue_manager, path_a, artist="Type Moon")
    job_b = _queue_to_kg_job(queue_manager, path_b, artist="type moon")

    service = KnowledgeGraphService(queue_manager=queue_manager)
    result_a = service.process_knowledge_graph_job(job_a)
    result_b = service.process_knowledge_graph_job(job_b)
    assert result_a is not None and result_b is not None

    path = service.shortest_path(f"image:{result_a.image_id}", f"image:{result_b.image_id}")
    assert path is not None


def test_knowledge_graph_updated_event_emitted(kg_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "gundam__amuro.jpg"
    image_path.write_bytes(b"fake")
    kg_job = _queue_to_kg_job(queue_manager, image_path)

    events: list[object] = []

    def callback(event: object) -> None:
        events.append(event)

    engine = KnowledgeGraphEngine(callback=callback)
    result = engine.process_path(image_path, metadata=kg_job.metadata)

    assert result is not None
    assert any(type(event).__name__ == "KnowledgeGraphUpdated" for event in events)


def test_service_skips_job_without_source_path(kg_env: None) -> None:
    queue_manager = QueueManager()
    service = KnowledgeGraphService(queue_manager=queue_manager)

    job = PipelineJob(queue_type=QueueType.SEARCH)
    result = service.process_knowledge_graph_job(job)

    assert result is None
