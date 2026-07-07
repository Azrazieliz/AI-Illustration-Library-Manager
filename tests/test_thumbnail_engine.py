"""Tests for the Thumbnail & Preview Engine (Commit 0011)."""
from __future__ import annotations

import io
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image as PillowImage

from engine.config import settings
from engine.database.database import database_manager
from engine.thumbnails import (
    ThumbnailCheckpoint,
    ThumbnailEngine,
    ThumbnailFormat,
    ThumbnailGenerator,
    ThumbnailService,
    ThumbnailSize,
    ThumbnailSpec,
    make_cache_key,
)
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.repositories.image_repository import ImageRepository
from engine.repositories.thumbnail_repository import ThumbnailRepository


# ------------------------------------------------------------------ #
# Fixture                                                              #
# ------------------------------------------------------------------ #


@pytest.fixture()
def thumb_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace", tmp_path)
    monkeypatch.setattr(settings, "database_directory", Path("database"))
    monkeypatch.setattr(settings, "log_directory", tmp_path / "logs")
    monkeypatch.setattr(settings, "cache_directory", tmp_path / "cache")
    monkeypatch.setattr(settings, "thumbnail_directory", Path("cache") / "thumbnails")
    monkeypatch.setattr(settings, "embedding_directory", tmp_path / "cache" / "embeddings")
    monkeypatch.setattr(settings, "knowledge_directory", tmp_path / "knowledge")
    monkeypatch.setattr(settings, "models_directory", tmp_path / "models")
    monkeypatch.setattr(settings, "datasets_directory", tmp_path / "datasets")
    monkeypatch.setattr(settings, "max_background_workers", 2)

    database_manager._engine = None
    database_manager._session_factory = None
    database_manager._initialized = False
    database_manager.__init__()


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def _make_image(path: Path, color: tuple[int, int, int] = (128, 64, 32),
                size: tuple[int, int] = (200, 150)) -> Path:
    img = PillowImage.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    path.write_bytes(buf.getvalue())
    return path


def _register(path: Path) -> int:
    repo = ImageRepository()
    return repo.create_image(
        original_path=str(path), filename=path.name, extension=path.suffix
    ).id


def _small_spec() -> ThumbnailSpec:
    return ThumbnailSpec(size=ThumbnailSize.SMALL, format=ThumbnailFormat.WEBP)


# ------------------------------------------------------------------ #
# make_cache_key                                                       #
# ------------------------------------------------------------------ #


def test_cache_key_changes_with_file_size(tmp_path: Path) -> None:
    p = tmp_path / "img.png"
    key1 = make_cache_key(p, 1000, 1234567890.0)
    key2 = make_cache_key(p, 2000, 1234567890.0)
    assert key1 != key2


def test_cache_key_changes_with_mtime(tmp_path: Path) -> None:
    p = tmp_path / "img.png"
    key1 = make_cache_key(p, 1000, 1234567890.0)
    key2 = make_cache_key(p, 1000, 1234567891.0)
    assert key1 != key2


def test_cache_key_stable_for_same_inputs(tmp_path: Path) -> None:
    p = tmp_path / "img.png"
    assert make_cache_key(p, 500, 999.0) == make_cache_key(p, 500, 999.0)


# ------------------------------------------------------------------ #
# ThumbnailGenerator – compute_dimensions                             #
# ------------------------------------------------------------------ #


def test_aspect_ratio_landscape(tmp_path: Path) -> None:
    w, h = ThumbnailGenerator._compute_dimensions(800, 400, 128)
    assert w == 128
    assert h == 64


def test_aspect_ratio_portrait(tmp_path: Path) -> None:
    w, h = ThumbnailGenerator._compute_dimensions(400, 800, 128)
    assert h == 128
    assert w == 64


def test_aspect_ratio_square(tmp_path: Path) -> None:
    w, h = ThumbnailGenerator._compute_dimensions(300, 300, 128)
    assert w == h == 128


def test_no_upscale(tmp_path: Path) -> None:
    """An image already smaller than the target must not be enlarged."""
    w, h = ThumbnailGenerator._compute_dimensions(64, 48, 128)
    assert w == 64
    assert h == 48


# ------------------------------------------------------------------ #
# Thumbnail generation                                                 #
# ------------------------------------------------------------------ #


def test_thumbnail_generated_on_disk(thumb_env: None, tmp_path: Path) -> None:
    p = _make_image(tmp_path / "img.png")
    _register(p)

    engine = ThumbnailEngine(specs=[_small_spec()])
    result = engine.process_path(p)

    assert result is not None
    assert result.from_cache is False
    assert len(result.thumbnails) == 1
    assert result.thumbnails[0].file_path.exists()
    assert result.thumbnails[0].file_path.stat().st_size > 0


def test_all_default_sizes_generated(thumb_env: None, tmp_path: Path) -> None:
    p = _make_image(tmp_path / "img.png", size=(600, 600))
    _register(p)

    engine = ThumbnailEngine()
    result = engine.process_path(p)

    assert result is not None
    assert len(result.thumbnails) == 3  # 128, 256, 512
    sizes = {t.spec.size for t in result.thumbnails}
    assert sizes == {128, 256, 512}


def test_aspect_ratio_preserved_in_output_file(thumb_env: None, tmp_path: Path) -> None:
    """200×100 source → 128px longest edge → 128×64 output."""
    p = _make_image(tmp_path / "wide.png", size=(200, 100))
    _register(p)

    engine = ThumbnailEngine(specs=[_small_spec()])
    result = engine.process_path(p)

    assert result is not None
    thumb = result.thumbnails[0]
    assert thumb.width == 128
    assert thumb.height == 64


def test_no_upscale_in_output_file(thumb_env: None, tmp_path: Path) -> None:
    """A 64×64 source must not be upscaled to 128px."""
    p = _make_image(tmp_path / "small.png", size=(64, 64))
    _register(p)

    engine = ThumbnailEngine(specs=[_small_spec()])
    result = engine.process_path(p)

    assert result is not None
    thumb = result.thumbnails[0]
    assert thumb.width <= 64
    assert thumb.height <= 64


# ------------------------------------------------------------------ #
# Cache                                                                #
# ------------------------------------------------------------------ #


def test_cache_hit_on_second_call(thumb_env: None, tmp_path: Path) -> None:
    p = _make_image(tmp_path / "img.png")
    _register(p)

    engine1 = ThumbnailEngine(specs=[_small_spec()])
    engine1.process_path(p)
    assert engine1.statistics.generated == 1
    assert engine1.statistics.cached == 0

    engine2 = ThumbnailEngine(specs=[_small_spec()])
    engine2.process_path(p)
    assert engine2.statistics.cached == 1
    assert engine2.statistics.generated == 0


def test_cache_invalidated_after_file_change(thumb_env: None, tmp_path: Path) -> None:
    p = _make_image(tmp_path / "img.png", color=(10, 20, 30))
    _register(p)

    engine1 = ThumbnailEngine(specs=[_small_spec()])
    engine1.process_path(p)
    assert engine1.statistics.generated == 1

    # Modify file and advance mtime by 2 s
    _make_image(p, color=(200, 200, 200))
    os.utime(p, (time.time() + 2, time.time() + 2))

    engine2 = ThumbnailEngine(specs=[_small_spec()])
    engine2.process_path(p)
    assert engine2.statistics.generated == 1
    assert engine2.statistics.cached == 0


def test_cache_hit_without_image_record(thumb_env: None, tmp_path: Path) -> None:
    """Files without an image record are still processed without crashing."""
    p = _make_image(tmp_path / "unregistered.png")

    engine = ThumbnailEngine(specs=[_small_spec()])
    result = engine.process_path(p)

    assert result is not None
    assert result.from_cache is False
    # image_id is -1 for unregistered files
    assert result.image_id == -1


# ------------------------------------------------------------------ #
# Corrupted image handling                                             #
# ------------------------------------------------------------------ #


def test_corrupted_image_is_counted_as_failed(thumb_env: None, tmp_path: Path) -> None:
    p = tmp_path / "corrupted.png"
    p.write_bytes(b"this is not a valid image file at all")
    _register(p)

    engine = ThumbnailEngine(specs=[_small_spec()])
    results = engine.process_paths([p])

    assert len(results) == 0
    assert engine.statistics.failed == 1
    assert engine.statistics.generated == 0


# ------------------------------------------------------------------ #
# Parallel generation                                                  #
# ------------------------------------------------------------------ #


def test_parallel_generation(thumb_env: None, tmp_path: Path) -> None:
    paths = []
    for i in range(6):
        p = _make_image(tmp_path / f"img{i}.png", color=(i * 40, i * 40, i * 40))
        _register(p)
        paths.append(p)

    engine = ThumbnailEngine(specs=[_small_spec()], max_workers=3)
    results = engine.process_paths(paths)

    assert len(results) == 6
    assert engine.statistics.generated == 6
    assert engine.statistics.failed == 0
    for result in results:
        assert result.thumbnails[0].file_path.exists()


# ------------------------------------------------------------------ #
# Crash recovery / checkpoint                                          #
# ------------------------------------------------------------------ #


def test_checkpoint_skips_processed_paths(thumb_env: None, tmp_path: Path) -> None:
    p1 = _make_image(tmp_path / "a.png", color=(10, 10, 10))
    p2 = _make_image(tmp_path / "b.png", color=(20, 20, 20))
    _register(p1)
    _register(p2)

    checkpoint = ThumbnailCheckpoint(processed_paths={str(p1.resolve())})

    engine = ThumbnailEngine(specs=[_small_spec()])
    results = engine.process_paths([p1, p2], checkpoint=checkpoint)

    # p1 was in checkpoint → skipped (counted as cached), p2 generated
    assert engine.statistics.generated == 1
    assert engine.statistics.cached == 1  # checkpoint skip counted as cached
    assert len(results) == 1
    assert results[0].source_path == str(p2)


def test_checkpoint_updated_after_generation(thumb_env: None, tmp_path: Path) -> None:
    p = _make_image(tmp_path / "img.png")
    _register(p)

    checkpoint = ThumbnailCheckpoint()
    engine = ThumbnailEngine(specs=[_small_spec()])
    engine.process_paths([p], checkpoint=checkpoint)

    assert str(p) in checkpoint.processed_paths


# ------------------------------------------------------------------ #
# Repository persistence                                               #
# ------------------------------------------------------------------ #


def test_thumbnail_record_persisted(thumb_env: None, tmp_path: Path) -> None:
    p = _make_image(tmp_path / "img.png")
    image_id = _register(p)

    engine = ThumbnailEngine(specs=[_small_spec()])
    engine.process_path(p)

    repo = ThumbnailRepository()
    record = repo.get_by_image_and_size(image_id, ThumbnailSize.SMALL)
    assert record is not None
    assert record.size == 128
    assert record.format == "webp"
    assert Path(record.file_path).exists()


def test_thumbnail_record_updated_on_file_change(thumb_env: None, tmp_path: Path) -> None:
    p = _make_image(tmp_path / "img.png", color=(1, 1, 1))
    image_id = _register(p)

    engine1 = ThumbnailEngine(specs=[_small_spec()])
    engine1.process_path(p)

    old_repo = ThumbnailRepository()
    old_key = old_repo.get_by_image_and_size(image_id, ThumbnailSize.SMALL).cache_key

    _make_image(p, color=(250, 250, 250))
    os.utime(p, (time.time() + 2, time.time() + 2))

    engine2 = ThumbnailEngine(specs=[_small_spec()])
    engine2.process_path(p)

    new_repo = ThumbnailRepository()
    new_key = new_repo.get_by_image_and_size(image_id, ThumbnailSize.SMALL).cache_key
    assert old_key != new_key


# ------------------------------------------------------------------ #
# Queue integration                                                    #
# ------------------------------------------------------------------ #


def test_service_publishes_metadata_job(thumb_env: None, tmp_path: Path) -> None:
    p = _make_image(tmp_path / "img.png")
    _register(p)

    qm = QueueManager()
    service = ThumbnailService(
        queue_manager=qm,
        engine=ThumbnailEngine(specs=[_small_spec()]),
    )

    job = PipelineJob(source_path=str(p), queue_type=QueueType.REVIEW)
    result = service.process_review_job(job)

    assert result is not None
    meta_job = qm.dequeue(QueueType.METADATA)
    assert meta_job is not None
    assert meta_job.metadata["image_id"] == result.image_id
    assert 128 in meta_job.metadata["thumbnail_sizes"]


def test_service_skips_job_without_source_path(thumb_env: None, tmp_path: Path) -> None:
    qm = QueueManager()
    service = ThumbnailService(queue_manager=qm)
    job = PipelineJob(source_path=None, queue_type=QueueType.REVIEW)
    assert service.process_review_job(job) is None
    assert qm.dequeue(QueueType.METADATA) is None


# ------------------------------------------------------------------ #
# Statistics                                                           #
# ------------------------------------------------------------------ #


def test_statistics_tracked(thumb_env: None, tmp_path: Path) -> None:
    p1 = _make_image(tmp_path / "a.png")
    p2 = tmp_path / "bad.png"
    p2.write_bytes(b"garbage")
    _register(p1)
    _register(p2)

    engine = ThumbnailEngine(specs=[_small_spec()])
    engine.process_paths([p1, p2])

    assert engine.statistics.processed == 2
    assert engine.statistics.generated == 1
    assert engine.statistics.failed == 1
    assert engine.statistics.elapsed_seconds >= 0.0
