"""Tests for the Automatic Tagging Engine (Commit 0017)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.database.models.tag_provenance import TagProvenance
from engine.embeddings import EmbeddingService, MockProvider
from engine.knowledge_graph import KnowledgeGraphEngine, KnowledgeGraphService
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import MockRecognitionProvider, RecognitionService
from engine.search import SearchService
from engine.tagging import RuleBasedTaggingBackend, TagKind, TaggingCheckpoint, TaggingEngine, TaggingService
from engine.repositories.image_repository import ImageRepository
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.tagging_repository import TaggingRepository


@pytest.fixture()
def tagging_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _build_tagging_job(queue_manager: QueueManager, path: Path, *, artist: str | None = None) -> PipelineJob:
    _register_image(path)

    embedding_service = EmbeddingService(queue_manager=queue_manager, provider=MockProvider())
    embedding_job = PipelineJob(source_path=str(path), queue_type=QueueType.EMBEDDING)
    assert embedding_service.process_embedding_job(embedding_job) is not None

    recognition_service = RecognitionService(
        queue_manager=queue_manager,
        provider=MockRecognitionProvider(),
    )
    recognition_job = queue_manager.dequeue(QueueType.RECOGNITION)
    assert recognition_job is not None
    recognition_result = recognition_service.process_recognition_job(recognition_job)
    assert recognition_result is not None

    search_service = SearchService(queue_manager=queue_manager)
    search_job = queue_manager.dequeue(QueueType.SEARCH)
    assert search_job is not None
    if artist:
        search_job.metadata["artist"] = artist
    assert search_service.process_search_job(search_job) is not None

    kg_job = queue_manager.dequeue(QueueType.SEARCH)
    assert kg_job is not None

    shared_kg_engine = KnowledgeGraphEngine()
    kg_service = KnowledgeGraphService(queue_manager=queue_manager, engine=shared_kg_engine)
    assert kg_service.process_knowledge_graph_job(kg_job) is not None

    tagging_job = queue_manager.dequeue(QueueType.SEARCH)
    assert tagging_job is not None
    assert tagging_job.metadata.get("stage") == "tagging"
    return tagging_job


def _rule_based_tagging_service(queue_manager: QueueManager) -> TaggingService:
    return TaggingService(
        queue_manager=queue_manager,
        engine=TaggingEngine(backend=RuleBasedTaggingBackend()),
    )


def test_service_processes_tagging_job(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "fate__saber+rin.jpg"
    image_path.write_bytes(b"fake")

    tagging_job = _build_tagging_job(queue_manager, image_path, artist="Type Moon")
    service = _rule_based_tagging_service(queue_manager)

    result = service.process_tagging_job(tagging_job)

    assert result is not None
    assert len(result.generated_tags) > 0


def test_checkpoint_skips_processed(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "bleach__ichigo.jpg"
    image_path.write_bytes(b"fake")

    tagging_job = _build_tagging_job(queue_manager, image_path)
    service = _rule_based_tagging_service(queue_manager)
    checkpoint = TaggingCheckpoint()
    checkpoint.add_processed(str(image_path.resolve()))

    result = service.process_tagging_job(tagging_job, checkpoint=checkpoint)

    assert result is None


def test_parallel_processing(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    jobs: list[PipelineJob] = []
    for i in range(3):
        path = tmp_path / f"series__char_{i}.jpg"
        path.write_bytes(b"fake")
        jobs.append(_build_tagging_job(queue_manager, path, artist="ArtistA"))

    service = _rule_based_tagging_service(queue_manager)
    results = service.process_tagging_jobs(jobs)

    assert len(results) == 3


def test_kind_thresholds_classification(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "one_piece__luffy+zoro.jpg"
    path.write_bytes(b"fake")
    job = _build_tagging_job(queue_manager, path)

    engine = TaggingEngine(
        backend=RuleBasedTaggingBackend(),
        suggested_threshold=0.4,
        inferred_threshold=0.6,
        confirmed_threshold=0.85,
    )
    result = engine.process_path(path, metadata=job.metadata)

    assert result is not None
    kinds = {tag.kind for tag in result.generated_tags}
    assert TagKind.SUGGESTED in kinds or TagKind.INFERRED in kinds or TagKind.CONFIRMED in kinds


def test_prevent_duplicate_tags(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "naruto__naruto.jpg"
    path.write_bytes(b"fake")
    job = _build_tagging_job(queue_manager, path)

    service = _rule_based_tagging_service(queue_manager)
    result1 = service.process_tagging_job(job)
    assert result1 is not None

    # Incremental re-tagging should not duplicate tags.
    result2 = service.process_tagging_job(job)
    assert result2 is not None

    repo = TaggingRepository()
    image = repo.get_image_by_path(path)
    assert image is not None
    names = [tag.name for tag in image.tags]
    assert len(names) == len(set(names))


def test_merge_equivalent_tags(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "sample__hero.jpg"
    path.write_bytes(b"fake")
    job = _build_tagging_job(queue_manager, path)

    engine = TaggingEngine(backend=RuleBasedTaggingBackend())
    result = engine.process_path(path, metadata={**(job.metadata or {}), "series": "JPG"})
    assert result is not None

    names = [tag.name for tag in result.generated_tags]
    assert "jpeg" in names or "jpg" not in names


def test_store_tagging_provenance(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "eva__asuka.jpg"
    path.write_bytes(b"fake")
    job = _build_tagging_job(queue_manager, path)

    service = _rule_based_tagging_service(queue_manager)
    result = service.process_tagging_job(job)
    assert result is not None

    repo = TaggingRepository()
    sample = result.generated_tags[0]
    provenance = repo.get_provenance(image_id=result.image_id, tag_name=sample.name)
    records = repo.list_provenance_records(image_id=result.image_id, tag_name=sample.name)
    image = repo.get_by_id(result.image_id)

    assert len(provenance) > 0
    assert image is not None
    assert [record.source for record in records] == provenance
    assert all(record.provenance_uuid == record.uuid for record in records)
    assert all(record.image_uuid == image.uuid for record in records)
    assert all(record.tag_id > 0 and record.approved is False for record in records)
    assert all(record.source_model is None and record.source_version is None and record.review_uuid is None for record in records)
    assert all(record.confidence == sample.confidence and record.version == 1 for record in records)
    assert repo.session.query(TagProvenance).count() >= len(records)


def test_semantic_neighbors_load_persisted_embedding_vectors(tagging_env: None, tmp_path: Path) -> None:
    def store(path: Path, vector: list[float], tag_name: str) -> int:
        image_id = _register_image(path)
        artifact = path.with_suffix(".npy")
        np.save(artifact, np.asarray(vector, dtype=np.float32), allow_pickle=False)
        embedding_repository = EmbeddingRepository()
        embedding_repository.create_embedding_record(
            image_id=image_id,
            vector_path=str(artifact),
            model_name="test-provider",
            model_version="1",
        )
        embedding_repository.commit()
        tagging_repository = TaggingRepository()
        image = tagging_repository.get_image_by_path(path)
        assert image is not None
        tag = tagging_repository.get_or_create_tag(name=tag_name)
        tagging_repository.assign_tag(image, tag)
        tagging_repository.commit_changes()
        return image_id

    target = store(tmp_path / "target.png", [1.0, 0.0, 0.0], "target")
    nearest = store(tmp_path / "nearest.png", [1.0, 0.0, 0.0], "nearest")
    _ = store(tmp_path / "distant.png", [0.0, 1.0, 0.0], "distant")

    neighbors = TaggingEngine()._semantic_neighbors(TaggingRepository(), target)

    assert neighbors[0]["image_id"] == nearest
    assert neighbors[0]["similarity"] == pytest.approx(1.0, rel=1e-6)
    assert neighbors[0]["tags"] == ["nearest"]


def test_default_engine_rejects_unconfigured_tagging_backend(tagging_env: None, tmp_path: Path) -> None:
    path = tmp_path / "unconfigured.png"
    path.write_bytes(b"image")
    _register_image(path)
    events: list[object] = []

    result = TaggingEngine(callback=events.append).process_path(path)

    assert result is None
    failure = next(event for event in events if type(event).__name__ == "TaggingFailed")
    assert "explicitly configured backend" in failure.error


def test_tagging_completed_event_emitted(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "gundam__amuro.jpg"
    path.write_bytes(b"fake")
    job = _build_tagging_job(queue_manager, path)

    events: list[object] = []

    def callback(event: object) -> None:
        events.append(event)

    engine = TaggingEngine(backend=RuleBasedTaggingBackend(), callback=callback)
    _ = engine.process_paths([path], metadata=job.metadata)

    assert any(type(event).__name__ == "TaggingCompleted" for event in events)


def test_service_skips_non_tagging_stage_job(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "nonstage.jpg"
    path.write_bytes(b"fake")
    _register_image(path)

    service = _rule_based_tagging_service(queue_manager)
    job = PipelineJob(source_path=str(path), queue_type=QueueType.SEARCH, metadata={"stage": "knowledge_graph"})

    result = service.process_tagging_job(job)

    assert result is None


def test_knowledge_graph_service_publishes_tagging_job(tagging_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "publish__job.jpg"
    path.write_bytes(b"fake")

    _register_image(path)
    kg_service = KnowledgeGraphService(queue_manager=queue_manager)
    job = PipelineJob(source_path=str(path), queue_type=QueueType.SEARCH, metadata={"stage": "knowledge_graph"})
    _ = kg_service.process_knowledge_graph_job(job)

    tagging_job = queue_manager.dequeue(QueueType.SEARCH)
    assert tagging_job is not None
    assert tagging_job.metadata.get("stage") == "tagging"
