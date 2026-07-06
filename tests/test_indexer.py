from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.indexer import IncrementalIndexer, IndexDecision, IndexerService
from engine.pipeline import PipelineJob, QueueManager, QueueType


@pytest.fixture()
def indexer_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_indexer_tracks_new_modified_unchanged_and_deleted(indexer_environment: None, tmp_path: Path) -> None:
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"one")

    indexer = IncrementalIndexer()
    results = indexer.index_paths([image_path])
    assert len(results) == 1
    assert indexer.statistics.new == 1

    # Advance the file's mtime by 2 seconds to guarantee a whole-second change
    # that survives the SQLite round-trip (stored as truncated naive UTC).
    new_mtime = time.time() + 2
    image_path.write_bytes(b"two")
    os.utime(image_path, (new_mtime, new_mtime))
    results = indexer.index_paths([image_path])
    assert indexer.statistics.modified == 1

    results = indexer.index_paths([image_path])
    assert indexer.statistics.unchanged == 1

    image_path.unlink()
    indexer.index_paths([])
    assert indexer.statistics.deleted == 1


def test_indexer_checkpoint_allows_restart(indexer_environment: None, tmp_path: Path) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"a")
    second.write_bytes(b"b")

    from engine.indexer.indexer_models import IndexerCheckpoint

    checkpoint = IndexerCheckpoint(root=str(tmp_path), processed_paths={str(first)})
    indexer = IncrementalIndexer()
    results = indexer.index_paths([first, second], checkpoint=checkpoint)

    assert len(results) == 1
    assert results[0].source_path == str(second)


def test_indexer_service_publishes_hash_jobs_for_new_and_modified(indexer_environment: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    service = IndexerService(queue_manager=queue_manager)

    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"one")
    service.process_discovery_job(PipelineJob(source_path=str(image_path), queue_type=QueueType.DISCOVERY))

    queued = queue_manager.dequeue(QueueType.HASH)
    assert queued is not None
    assert queued.source_path == str(image_path)

    # Modify file with an explicit mtime advance so it is seen as modified
    new_mtime = time.time() + 2
    image_path.write_bytes(b"two")
    os.utime(image_path, (new_mtime, new_mtime))
    service.process_discovery_job(PipelineJob(source_path=str(image_path), queue_type=QueueType.DISCOVERY))
    queued = queue_manager.dequeue(QueueType.HASH)
    assert queued is not None
