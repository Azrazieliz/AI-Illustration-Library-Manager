from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from engine.config import settings
from engine.database import get_database_manager
from engine.embeddings import (
    CLIPProvider,
    EmbeddingCache,
    EmbeddingCheckpoint,
    EmbeddingEngine,
    EmbeddingService,
    EmbeddingStatistics,
    MockProvider,
    get_provider,
)
from engine.embeddings.embedding_models import ExtractedEmbedding
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.image_repository import ImageRepository


@pytest.fixture
def embedding_env() -> None:
    """Set up embedding test environment."""
    manager = get_database_manager()
    manager.initialize()
    yield


# ================================================================ #
# Provider Tests                                                    #
# ================================================================ #


def test_mock_provider_initialization(embedding_env: None) -> None:
    """Test mock provider initialization."""
    provider = MockProvider(dimensions=512)
    provider.initialize()
    assert provider.get_dimensions() == 512
    assert provider.get_provider_name() == "mock"


def test_mock_provider_extract_deterministic(embedding_env: None, tmp_path: Path) -> None:
    """Test mock provider produces deterministic embeddings."""
    provider = MockProvider(dimensions=256)
    provider.initialize()

    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake image data")

    vec1 = provider.extract(img_path)
    vec2 = provider.extract(img_path)

    assert len(vec1) == 256
    assert len(vec2) == 256
    assert vec1 == vec2


def test_get_provider_mock(embedding_env: None) -> None:
    """Test get_provider factory for mock."""
    provider = get_provider(provider_type="mock", dimensions=384)
    provider.initialize()
    assert provider.get_dimensions() == 384
    assert provider.get_provider_name() == "mock"


def test_provider_extract_embedding(embedding_env: None, tmp_path: Path) -> None:
    """Test provider.extract_embedding wraps result."""
    provider = MockProvider(dimensions=128)
    provider.initialize()

    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    embedding = provider.extract_embedding(image_id=123, path=img_path)

    assert embedding.image_id == 123
    assert embedding.dimensions == 128
    assert embedding.model_name == "mock"
    assert embedding.provider_name == "mock"
    assert len(embedding.embedding_vector) == 128


# ================================================================ #
# Cache Tests                                                       #
# ================================================================ #


def test_cache_put_get_memory(embedding_env: None) -> None:
    """Test in-memory cache put and get."""
    cache = EmbeddingCache()
    vector = [0.1, 0.2, 0.3, 0.4]

    cache.put(image_id=1, model_name="test_model", vector=vector)
    retrieved = cache.get(image_id=1, model_name="test_model")

    assert retrieved == vector


def test_cache_miss_returns_none(embedding_env: None) -> None:
    """Test cache miss returns None."""
    cache = EmbeddingCache()
    result = cache.get(image_id=999, model_name="missing")
    assert result is None


def test_cache_disk_persistence(embedding_env: None) -> None:
    """Test disk-based cache persistence."""
    with TemporaryDirectory() as tmp_dir:
        cache = EmbeddingCache(cache_dir=tmp_dir)
        vector = [0.1, 0.2, 0.3]

        cache.put(image_id=42, model_name="test_model", vector=vector)

        # Load from disk
        cache2 = EmbeddingCache(cache_dir=tmp_dir)
        retrieved = cache2.get(image_id=42, model_name="test_model")

        assert retrieved == vector


def test_cache_clear(embedding_env: None) -> None:
    """Test cache clearing."""
    cache = EmbeddingCache()
    cache.put(1, "model", [0.1, 0.2])
    cache.put(2, "model", [0.3, 0.4])

    cache.clear()

    assert cache.get(1, "model") is None
    assert cache.get(2, "model") is None


# ================================================================ #
# Repository Tests                                                  #
# ================================================================ #


def test_embedding_repository_create(embedding_env: None, tmp_path: Path) -> None:
    """Test creating an embedding record."""
    # Create an image first
    image_repo = ImageRepository()
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    # Create embedding record
    embedding_repo = EmbeddingRepository()
    embedding = embedding_repo.create_embedding_record(
        image_id=image.id,
        vector_path="/path/to/vector.bin",
        model_name="test_model",
        model_version="1.0.0",
    )
    embedding_repo.commit()

    # Retrieve
    retrieved = embedding_repo.get_by_image_id(image.id)
    assert retrieved is not None
    assert retrieved.model_name == "test_model"
    assert retrieved.model_version == "1.0.0"


def test_embedding_repository_update(embedding_env: None, tmp_path: Path) -> None:
    """Test updating an embedding record."""
    image_repo = ImageRepository()
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    embedding_repo = EmbeddingRepository()
    embedding = embedding_repo.create_embedding_record(
        image_id=image.id,
        vector_path="/path/v1.bin",
        model_name="model_v1",
        model_version="1.0.0",
    )
    embedding_repo.commit()

    # Update
    updated = embedding_repo.update_embedding_record(
        embedding,
        vector_path="/path/v2.bin",
        model_version="2.0.0",
    )
    embedding_repo.commit()

    retrieved = embedding_repo.get_by_image_id(image.id)
    assert retrieved.vector_path == "/path/v2.bin"
    assert retrieved.model_version == "2.0.0"


# ================================================================ #
# Engine Tests                                                      #
# ================================================================ #


def test_engine_process_single_path(embedding_env: None, tmp_path: Path) -> None:
    """Test engine processes single path."""
    # Create test image
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake image")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    # Process with engine
    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider)

    result = engine.process_path(img_path)

    assert result is not None
    assert result.image_id == image.id
    assert result.embedding.dimensions == 256


def test_engine_process_multiple_paths(embedding_env: None, tmp_path: Path) -> None:
    """Test engine processes multiple paths."""
    image_repo = ImageRepository()

    paths = []
    for i in range(3):
        img_path = tmp_path / f"test_{i}.jpg"
        img_path.write_bytes(b"fake")
        image = image_repo.create_image(
            original_path=str(img_path),
            filename=f"test_{i}.jpg",
            extension="jpg",
        )
        paths.append(img_path)
    image_repo.commit()

    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider)

    results = engine.process_paths(paths)

    assert len(results) == 3
    assert all(r.embedding.dimensions == 256 for r in results)


def test_engine_checkpoint_skips_processed(embedding_env: None, tmp_path: Path) -> None:
    """Test checkpoint prevents reprocessing."""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider)

    checkpoint = EmbeddingCheckpoint()
    checkpoint.add_processed(img_path)

    results = engine.process_paths([img_path], checkpoint=checkpoint)

    assert len(results) == 0
    assert engine.statistics.skipped == 1


def test_engine_statistics_tracked(embedding_env: None, tmp_path: Path) -> None:
    """Test statistics are properly tracked."""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider)

    engine.process_paths([img_path])

    assert engine.statistics.processed == 1
    assert engine.statistics.embedded == 1
    assert engine.statistics.failed == 0


def test_engine_missing_image_record(embedding_env: None, tmp_path: Path) -> None:
    """Test engine handles missing image record."""
    img_path = tmp_path / "unknown.jpg"
    img_path.write_bytes(b"fake")

    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider)

    result = engine.process_path(img_path)

    assert result is None
    assert engine.statistics.skipped == 1


# ================================================================ #
# Service Tests                                                     #
# ================================================================ #


def test_service_publishes_embedding_job(embedding_env: None, tmp_path: Path) -> None:
    """Test service integration with pipeline."""
    # Create test image
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    # Process via service
    queue_manager = QueueManager()
    service = EmbeddingService(queue_manager=queue_manager)

    job = PipelineJob(source_path=str(img_path), queue_type=QueueType.EMBEDDING)
    result = service.process_embedding_job(job)

    assert result is not None
    assert result.image_id == image.id


def test_service_skips_job_without_source_path(embedding_env: None) -> None:
    """Test service skips jobs without source_path."""
    queue_manager = QueueManager()
    service = EmbeddingService(queue_manager=queue_manager)

    job = PipelineJob(queue_type=QueueType.EMBEDDING)
    result = service.process_embedding_job(job)

    assert result is None


# ================================================================ #
# Checkpoint Recovery Tests                                         #
# ================================================================ #


def test_checkpoint_updated_after_extraction(embedding_env: None, tmp_path: Path) -> None:
    """Test checkpoint is updated after extraction."""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider)

    checkpoint = EmbeddingCheckpoint()
    results = engine.process_paths([img_path], checkpoint=checkpoint)

    assert len(results) > 0
    assert checkpoint.is_processed(img_path)


def test_checkpoint_skips_batch(embedding_env: None, tmp_path: Path) -> None:
    """Test checkpoint prevents batch reprocessing."""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider)

    checkpoint = EmbeddingCheckpoint()

    # First run
    results1 = engine.process_paths([img_path], checkpoint=checkpoint)
    stats1 = engine.statistics

    # Second run with checkpoint
    results2 = engine.process_paths([img_path], checkpoint=checkpoint)
    stats2 = engine.statistics

    assert len(results1) > 0
    assert len(results2) == 0
    assert stats2.skipped >= 1


# ================================================================ #
# Event Tests                                                       #
# ================================================================ #


def test_embedding_events_fired(embedding_env: None, tmp_path: Path) -> None:
    """Test embedding events are fired."""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    events = []

    def callback(event: object) -> None:
        events.append(event)

    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider, callback=callback)

    engine.process_paths([img_path])

    # Should have Started, Extracted, Completed events
    event_types = {type(e).__name__ for e in events}
    assert "EmbeddingCompleted" in event_types


# ================================================================ #
# Thread Safety Tests                                               #
# ================================================================ #


def test_parallel_generation(embedding_env: None, tmp_path: Path) -> None:
    """Test parallel embedding generation is thread-safe."""
    image_repo = ImageRepository()

    paths = []
    for i in range(5):
        img_path = tmp_path / f"test_{i}.jpg"
        img_path.write_bytes(b"fake")
        image = image_repo.create_image(
            original_path=str(img_path),
            filename=f"test_{i}.jpg",
            extension="jpg",
        )
        paths.append(img_path)
    image_repo.commit()

    provider = MockProvider(dimensions=128)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider, max_workers=3)

    results = engine.process_paths(paths)

    assert len(results) == 5
    assert engine.statistics.embedded == 5


# ================================================================ #
# Duplicate Execution Prevention                                    #
# ================================================================ #


def test_duplicate_execution_prevention(embedding_env: None, tmp_path: Path) -> None:
    """Test that duplicate executions are prevented by database check."""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    provider = MockProvider(dimensions=256)
    provider.initialize()
    engine = EmbeddingEngine(provider=provider)

    # Run twice without checkpoint
    results1 = engine.process_paths([img_path])
    results2 = engine.process_paths([img_path])

    # First run should succeed, second run should skip (embedding already exists)
    assert len(results1) > 0
    assert len(results2) == 0  # Skipped because embedding exists
    assert engine.statistics.skipped >= 1


def test_cache_prevents_duplicate_embedding(embedding_env: None, tmp_path: Path) -> None:
    """Test that cache prevents re-embedding same image."""
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(b"fake")

    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(img_path),
        filename="test.jpg",
        extension="jpg",
    )
    image_repo.commit()

    cache = EmbeddingCache()
    provider = MockProvider(dimensions=256)
    provider.initialize()

    # Pre-populate cache
    cache.put(image.id, provider.model_name, [0.1] * 256)

    # Create engine with cache
    from engine.embeddings.embedding_worker import EmbeddingWorker

    worker = EmbeddingWorker(
        provider=provider,
        cache=cache,
    )

    # Should skip due to cache
    result = worker._process_one(img_path)
    assert result is None
    assert worker.statistics.skipped == 1
