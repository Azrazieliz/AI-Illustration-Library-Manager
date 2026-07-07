"""Tests for the Collection & Smart Library Management subsystem (Commit 0020)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.collections import (
    CollectionAction,
    CollectionCheckpoint,
    CollectionEngine,
    CollectionJobPayload,
    CollectionKind,
    CollectionService,
)
from engine.config import settings
from engine.database.database import database_manager
from engine.dataset import DatasetService
from engine.embeddings import EmbeddingService
from engine.export import ExportService
from engine.knowledge_graph import KnowledgeGraphService
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import RecognitionService
from engine.repositories.collection_repository import CollectionRepository
from engine.repositories.export_repository import ExportRepository
from engine.repositories.image_repository import ImageRepository
from engine.search import SearchService
from engine.tagging import TaggingService


@pytest.fixture()
def collection_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    CollectionRepository.reset_state()


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

    for item in deferred:
        queue_manager.enqueue(QueueType.SEARCH, item)

    assert selected is not None
    return selected


def _build_collection_job(
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
    if metadata:
        dataset_job.metadata.update(metadata)
    dataset_service = DatasetService(queue_manager=queue_manager)
    assert dataset_service.process_dataset_job(dataset_job) is not None

    export_job = _dequeue_search_job(queue_manager, expected_stage="export")
    if metadata:
        export_job.metadata.update(metadata)
    export_service = ExportService(queue_manager=queue_manager)
    assert export_service.process_export_job(export_job) is not None

    if keep_in_queue:
        collection_job = _dequeue_search_job(queue_manager, expected_stage="collection")
        queue_manager.enqueue(QueueType.SEARCH, collection_job)
    else:
        collection_job = _dequeue_search_job(queue_manager, expected_stage="collection")

    assert collection_job.metadata.get("stage") == "collection"
    return collection_job


def test_create_static_collection(collection_env: None) -> None:
    service = CollectionService()
    result = service.create_collection(name="Favorites", kind=CollectionKind.STATIC)

    assert result.changed is True
    summary = service.summary(result.collection_id)
    assert summary is not None
    assert summary.name == "Favorites"
    assert summary.kind == CollectionKind.STATIC


def test_create_smart_collection(collection_env: None) -> None:
    service = CollectionService()
    result = service.create_collection(
        name="High Confidence",
        kind=CollectionKind.SMART,
        smart_rule={"min_confidence": 0.0},
    )

    assert result.changed is True
    summary = service.summary(result.collection_id)
    assert summary is not None
    assert summary.kind == CollectionKind.SMART


def test_rename_collection(collection_env: None) -> None:
    service = CollectionService()
    created = service.create_collection(name="Old Name")
    payload = CollectionJobPayload(
        action=CollectionAction.RENAME,
        collection_id=created.collection_id,
        new_name="New Name",
    )

    result = service.engine.process_job(payload)

    assert result is not None
    summary = service.summary(created.collection_id)
    assert summary is not None
    assert summary.name == "New Name"


def test_delete_collection(collection_env: None) -> None:
    service = CollectionService()
    created = service.create_collection(name="Delete Me")

    payload = CollectionJobPayload(action=CollectionAction.DELETE, collection_id=created.collection_id)
    result = service.engine.process_job(payload)

    assert result is not None
    assert service.summary(created.collection_id) is None


def test_nested_collections_hierarchy(collection_env: None) -> None:
    service = CollectionService()
    root = service.create_collection(name="Root")
    child = service.create_collection(name="Child", parent_id=root.collection_id)
    _ = service.create_collection(name="Grandchild", parent_id=child.collection_id)

    tree = service.hierarchy()

    assert len(tree) == 1
    assert tree[0].name == "Root"
    assert len(tree[0].children) == 1
    assert tree[0].children[0].name == "Child"
    assert len(tree[0].children[0].children) == 1


def test_collection_metadata_statistics_thumbnail(collection_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "meta_thumb__sample.jpg"
    image_path.write_bytes(b"fake")
    job = _build_collection_job(queue_manager, image_path)

    service = CollectionService(queue_manager=queue_manager)
    processed = service.process_collection_job(job)
    assert processed is not None

    payload = CollectionJobPayload(
        action=CollectionAction.UPDATE_METADATA,
        collection_id=processed.collection_id,
        metadata={"description": "Primary collection", "color": "blue"},
    )
    updated = service.engine.process_job(payload)
    assert updated is not None

    summary = service.summary(processed.collection_id)
    assert summary is not None
    assert summary.image_count == 1
    assert summary.thumbnail_path is not None


def test_image_membership_add_remove(collection_env: None, tmp_path: Path) -> None:
    path = tmp_path / "membership__sample.jpg"
    path.write_bytes(b"fake")
    image_id = _register_image(path)

    service = CollectionService()
    collection = service.create_collection(name="Membership")

    added = service.engine.add_image(collection.collection_id, image_id)
    removed = service.engine.remove_image(collection.collection_id, image_id)

    assert added.changed is True
    assert removed.changed is True


def test_bulk_add_remove(collection_env: None, tmp_path: Path) -> None:
    image_ids: list[int] = []
    for idx in range(3):
        path = tmp_path / f"bulk_add_remove__{idx}.jpg"
        path.write_bytes(b"fake")
        image_ids.append(_register_image(path))

    service = CollectionService()
    collection = service.create_collection(name="Bulk")

    added = service.engine.bulk_add_images(collection.collection_id, image_ids)
    removed = service.engine.bulk_remove_images(collection.collection_id, image_ids[:2])

    assert len(added.affected_image_ids) == 3
    assert len(removed.affected_image_ids) == 2


def test_bulk_move(collection_env: None, tmp_path: Path) -> None:
    image_ids: list[int] = []
    for idx in range(4):
        path = tmp_path / f"bulk_move__{idx}.jpg"
        path.write_bytes(b"fake")
        image_ids.append(_register_image(path))

    service = CollectionService()
    source = service.create_collection(name="Source")
    target = service.create_collection(name="Target")
    _ = service.engine.bulk_add_images(source.collection_id, image_ids)

    moved = service.engine.bulk_move_images(
        source_collection_id=source.collection_id,
        target_collection_id=target.collection_id,
        image_ids=image_ids[:3],
    )

    assert len(moved.affected_image_ids) == 3
    source_summary = service.summary(source.collection_id)
    target_summary = service.summary(target.collection_id)
    assert source_summary is not None and source_summary.image_count == 1
    assert target_summary is not None and target_summary.image_count == 3


def test_smart_collection_refresh(collection_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    for idx in range(2):
        path = tmp_path / f"smart_refresh__{idx}.jpg"
        path.write_bytes(b"fake")
        _ = _build_collection_job(queue_manager, path)

    service = CollectionService(queue_manager=queue_manager)
    smart = service.create_collection(
        name="Smart",
        kind=CollectionKind.SMART,
        smart_rule={"min_confidence": 0.0},
    )
    refreshed = service.engine.refresh_smart_collection(smart.collection_id)

    assert refreshed.changed is True
    summary = service.summary(smart.collection_id)
    assert summary is not None
    assert summary.image_count >= 1


def test_collection_events_and_statistics(collection_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "events_stats.jpg")
    events: list[object] = []

    def callback(event: object) -> None:
        events.append(event)

    engine = CollectionEngine(callback=callback)
    created = engine.create_collection(name="Events")
    payloads = [
        CollectionJobPayload(action=CollectionAction.ADD_IMAGE, collection_id=created.collection_id, image_id=image_id),
        CollectionJobPayload(action=CollectionAction.ADD_IMAGE, collection_id=created.collection_id, image_id=image_id),
    ]
    _ = engine.process_jobs(payloads)

    assert engine.statistics.processed >= 2
    assert any(type(event).__name__ == "CollectionCompleted" for event in events)


def test_checkpoint_recovery(collection_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "checkpoint.jpg")
    service = CollectionService()
    created = service.create_collection(name="Checkpoint")

    checkpoint = CollectionCheckpoint()
    checkpoint.add_processed(CollectionAction.ADD_IMAGE, created.collection_id, image_id)

    payload = CollectionJobPayload(action=CollectionAction.ADD_IMAGE, collection_id=created.collection_id, image_id=image_id)
    result = service.engine.process_job(payload, checkpoint=checkpoint)

    assert result is None


def test_thread_safety(collection_env: None, tmp_path: Path) -> None:
    image_ids: list[int] = []
    for idx in range(12):
        path = tmp_path / f"threadsafe__{idx}.jpg"
        path.write_bytes(b"fake")
        image_ids.append(_register_image(path))

    engine = CollectionEngine(max_workers=4)
    created = engine.create_collection(name="ThreadSafe")
    payloads = [
        CollectionJobPayload(action=CollectionAction.ADD_IMAGE, collection_id=created.collection_id, image_id=image_id)
        for image_id in image_ids
    ]
    results = engine.process_jobs(payloads)

    assert len(results) == 12
    summary = engine.summary(created.collection_id)
    assert summary is not None
    assert summary.image_count == 12


def test_pipeline_integration_from_export(collection_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    image_path = tmp_path / "pipeline__sample.jpg"
    image_path.write_bytes(b"fake")
    _ = _build_collection_job(queue_manager, image_path, keep_in_queue=True)

    collection_job = _dequeue_search_job(queue_manager, expected_stage="collection")
    assert collection_job.metadata.get("stage") == "collection"


def test_rebuild_mode_like_behavior_idempotency(collection_env: None, tmp_path: Path) -> None:
    image_id = _register_image(tmp_path / "idempotent.jpg")
    service = CollectionService()
    created = service.create_collection(name="Idempotent")

    first = service.engine.add_image(created.collection_id, image_id)
    second = service.engine.add_image(created.collection_id, image_id)

    assert first.changed is True
    assert second.changed is False


def test_process_collection_job_from_pipeline(collection_env: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    path = tmp_path / "process_job.jpg"
    path.write_bytes(b"fake")
    job = _build_collection_job(queue_manager, path)

    service = CollectionService(queue_manager=queue_manager)
    result = service.process_collection_job(job)

    assert result is not None
    summary = service.summary(result.collection_id)
    assert summary is not None
    assert summary.image_count >= 1
