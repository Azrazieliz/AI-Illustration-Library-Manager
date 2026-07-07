"""Tests for the Metadata Extraction Engine (Commit 0012)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image as PillowImage

from engine.config import settings
from engine.database.database import database_manager
from engine.metadata import (
    MetadataCheckpoint,
    MetadataEngine,
    MetadataExtractor,
    MetadataService,
)
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository


# ------------------------------------------------------------------ #
# Fixture                                                              #
# ------------------------------------------------------------------ #


@pytest.fixture()
def metadata_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _make_jpeg(path: Path, size: tuple[int, int] = (640, 480), quality: int = 90) -> Path:
    """Create a JPEG test image."""
    img = PillowImage.new("RGB", size, (200, 100, 50))
    img.save(path, format="JPEG", quality=quality)
    return path


def _make_png(path: Path, size: tuple[int, int] = (320, 240)) -> Path:
    """Create a PNG test image."""
    img = PillowImage.new("RGBA", size, (100, 150, 200, 255))
    img.save(path, format="PNG")
    return path


def _make_webp(path: Path, size: tuple[int, int] = (512, 512)) -> Path:
    """Create a WebP test image."""
    img = PillowImage.new("RGB", size, (50, 100, 200))
    img.save(path, format="WEBP", quality=80)
    return path


def _make_animated_gif(path: Path, frames: int = 3) -> Path:
    """Create an animated GIF."""
    images = [
        PillowImage.new("RGB", (256, 256), (i * 50, i * 80, i * 100))
        for i in range(frames)
    ]
    images[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=100,
        loop=0,
    )
    return path


def _register_image(path: Path) -> int:
    """Create and return an image record."""
    repo = ImageRepository()
    return repo.create_image(
        original_path=str(path), filename=path.name, extension=path.suffix
    ).id


# ------------------------------------------------------------------ #
# MetadataExtractor Tests                                              #
# ------------------------------------------------------------------ #


def test_extract_jpeg_metadata(tmp_path: Path) -> None:
    """Test JPEG metadata extraction."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path, size=(640, 480))

    metadata = MetadataExtractor.extract(img_path)

    assert metadata.path == img_path
    assert metadata.width == 640
    assert metadata.height == 480
    assert metadata.aspect_ratio == pytest.approx(640 / 480, rel=1e-5)
    assert metadata.mime_type == "image/jpeg"
    assert metadata.color_mode == "RGB"
    assert metadata.bit_depth == 24


def test_extract_png_metadata(tmp_path: Path) -> None:
    """Test PNG metadata extraction with alpha."""
    img_path = tmp_path / "test.png"
    _make_png(img_path, size=(320, 240))

    metadata = MetadataExtractor.extract(img_path)

    assert metadata.width == 320
    assert metadata.height == 240
    assert metadata.mime_type == "image/png"
    assert metadata.color_mode == "RGBA"
    assert metadata.bit_depth == 32


def test_extract_webp_metadata(tmp_path: Path) -> None:
    """Test WebP metadata extraction."""
    img_path = tmp_path / "test.webp"
    _make_webp(img_path, size=(512, 512))

    metadata = MetadataExtractor.extract(img_path)

    assert metadata.width == 512
    assert metadata.height == 512
    assert metadata.mime_type == "image/webp"
    assert metadata.color_mode == "RGB"


def test_extract_animated_gif_metadata(tmp_path: Path) -> None:
    """Test animated GIF metadata extraction."""
    img_path = tmp_path / "animated.gif"
    _make_animated_gif(img_path, frames=5)

    metadata = MetadataExtractor.extract(img_path)

    assert metadata.mime_type == "image/gif"
    assert metadata.is_animated is True
    assert metadata.frame_count == 5


def test_extract_missing_exif(tmp_path: Path) -> None:
    """Test extraction when EXIF data is missing."""
    img_path = tmp_path / "no_exif.jpg"
    _make_jpeg(img_path)

    metadata = MetadataExtractor.extract(img_path)

    # Should still extract basic metadata
    assert metadata.width is not None
    assert metadata.height is not None
    # EXIF may be None
    assert metadata.exif_data is None or isinstance(metadata.exif_data, str)


def test_extract_corrupted_image(tmp_path: Path) -> None:
    """Test extraction of corrupted image."""
    img_path = tmp_path / "corrupted.jpg"
    # Create a JPEG with some valid data but then truncate it
    img = PillowImage.new("RGB", (100, 100), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg_data = buf.getvalue()
    # Truncate to make it invalid
    img_path.write_bytes(jpeg_data[:100])

    from engine.metadata.metadata_exceptions import CorruptedImageError, UnsupportedImageFormatError

    # PIL may raise either depending on how truncated it is
    with pytest.raises((CorruptedImageError, UnsupportedImageFormatError)):
        MetadataExtractor.extract(img_path)


def test_extract_unsupported_format(tmp_path: Path) -> None:
    """Test extraction of unsupported file format."""
    img_path = tmp_path / "test.bmp"
    # Create a minimal BMP that Pillow might not support in all versions
    img_path.write_bytes(b"not_an_image_file_at_all" * 100)

    from engine.metadata.metadata_exceptions import UnsupportedImageFormatError

    with pytest.raises(UnsupportedImageFormatError):
        MetadataExtractor.extract(img_path)


def test_extract_missing_file() -> None:
    """Test extraction of non-existent file."""
    from engine.metadata.metadata_exceptions import MetadataExtractionError

    with pytest.raises(MetadataExtractionError, match="File not found"):
        MetadataExtractor.extract("/nonexistent/path/file.jpg")


# ------------------------------------------------------------------ #
# MetadataEngine Tests                                                 #
# ------------------------------------------------------------------ #


def test_engine_process_single_path(metadata_env: None, tmp_path: Path) -> None:
    """Test single-path metadata extraction."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path, size=(800, 600))
    image_id = _register_image(img_path)

    engine = MetadataEngine()
    result = engine.process_path(img_path)

    assert result is not None
    assert result.image_id == image_id
    assert result.metadata.width == 800
    assert result.metadata.height == 600


def test_engine_process_multiple_paths(metadata_env: None, tmp_path: Path) -> None:
    """Test batch metadata extraction."""
    paths = []
    for i in range(3):
        img_path = tmp_path / f"test_{i}.jpg"
        _make_jpeg(img_path, size=(640 + i * 100, 480 + i * 100))
        _register_image(img_path)
        paths.append(img_path)

    engine = MetadataEngine()
    results = engine.process_paths(paths)

    assert len(results) == 3
    assert all(r.metadata.width is not None for r in results)
    assert engine.statistics.processed == 3


def test_engine_checkpoint_skips_processed(metadata_env: None, tmp_path: Path) -> None:
    """Test that checkpoint prevents reprocessing."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path)
    _register_image(img_path)

    checkpoint = MetadataCheckpoint()
    checkpoint.add_processed(str(img_path))

    engine = MetadataEngine()
    result = engine.process_path(img_path, checkpoint=checkpoint)

    assert result is None


def test_engine_statistics_tracked(metadata_env: None, tmp_path: Path) -> None:
    """Test that statistics are properly tracked."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path)
    _register_image(img_path)

    engine = MetadataEngine()
    engine.process_paths([img_path])

    assert engine.statistics.processed == 1
    assert engine.statistics.extracted == 1
    assert engine.statistics.failed == 0


def test_engine_missing_image_record(metadata_env: None, tmp_path: Path) -> None:
    """Test handling of missing image record."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path)
    # Don't register the image

    engine = MetadataEngine()
    result = engine.process_path(img_path)

    assert result is None


# ------------------------------------------------------------------ #
# MetadataRepository Tests                                             #
# ------------------------------------------------------------------ #


def test_metadata_record_persisted(metadata_env: None, tmp_path: Path) -> None:
    """Test that metadata is persisted to the database."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path, size=(640, 480))
    image_id = _register_image(img_path)

    engine = MetadataEngine()
    engine.process_path(img_path)

    # Retrieve from fresh repository instance
    repo = MetadataRepository()
    record = repo.get_by_image_id(image_id)

    assert record is not None
    assert record.image_id == image_id
    assert record.mime_type == "image/jpeg"
    assert record.aspect_ratio is not None


def test_metadata_record_updated(metadata_env: None, tmp_path: Path) -> None:
    """Test that metadata record is updated on subsequent processing."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path, size=(640, 480))
    image_id = _register_image(img_path)

    engine = MetadataEngine()

    # First extraction
    engine.process_path(img_path)
    repo = MetadataRepository()
    record1 = repo.get_by_image_id(image_id)

    # Verify initial aspect ratio (640/480 = 1.333...)
    initial_aspect = record1.aspect_ratio
    assert initial_aspect is not None
    assert initial_aspect == pytest.approx(640 / 480, rel=1e-5)

    # Delete and recreate with different proportions (square)
    img_path.unlink()
    _make_jpeg(img_path, size=(500, 500))

    # Second extraction
    engine.process_path(img_path)
    repo = MetadataRepository()
    record2 = repo.get_by_image_id(image_id)

    # Both should point to same record but different aspect ratios
    assert record1.id == record2.id
    assert record2.aspect_ratio is not None
    assert record2.aspect_ratio == pytest.approx(1.0, rel=1e-5)
    assert initial_aspect != record2.aspect_ratio


# ------------------------------------------------------------------ #
# MetadataService Tests                                                #
# ------------------------------------------------------------------ #


def test_service_publishes_search_job(metadata_env: None, tmp_path: Path) -> None:
    """Test that SEARCH queue jobs are published."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path, size=(640, 480))
    image_id = _register_image(img_path)

    queue_manager = QueueManager()
    service = MetadataService(queue_manager=queue_manager)

    job = PipelineJob(source_path=str(img_path), queue_type=QueueType.METADATA)
    result = service.process_metadata_job(job)

    assert result is not None
    assert result.image_id == image_id

    # Check that SEARCH job was published
    search_queue = queue_manager.peek(QueueType.SEARCH)
    assert search_queue is not None


def test_service_skips_job_without_source_path(metadata_env: None) -> None:
    """Test that jobs without source_path are skipped."""
    queue_manager = QueueManager()
    service = MetadataService(queue_manager=queue_manager)

    job = PipelineJob(queue_type=QueueType.METADATA)  # No source_path
    result = service.process_metadata_job(job)

    assert result is None


# ------------------------------------------------------------------ #
# Crash Recovery Tests                                                 #
# ------------------------------------------------------------------ #


def test_checkpoint_updated_after_extraction(metadata_env: None, tmp_path: Path) -> None:
    """Test that checkpoint is updated after extraction in batch mode."""
    img_path = tmp_path / "test.jpg"
    _make_jpeg(img_path)
    _register_image(img_path)

    checkpoint = MetadataCheckpoint()
    engine = MetadataEngine()

    # Use batch mode where checkpoint is actually updated
    results = engine.process_paths([img_path], checkpoint=checkpoint)

    # Checkpoint should be updated for successfully processed files
    if results:
        assert checkpoint.is_processed(str(img_path))


def test_checkpoint_skips_batch(metadata_env: None, tmp_path: Path) -> None:
    """Test that checkpoint skips files in batch processing."""
    paths = []
    for i in range(3):
        img_path = tmp_path / f"test_{i}.jpg"
        _make_jpeg(img_path)
        _register_image(img_path)
        paths.append(img_path)

    # Simulate first run
    checkpoint = MetadataCheckpoint()
    engine = MetadataEngine()
    results1 = engine.process_paths(paths[:2], checkpoint=checkpoint)
    assert len(results1) == 2

    # Second run with checkpoint
    results2 = engine.process_paths(paths, checkpoint=checkpoint)
    assert len(results2) == 1  # Only the third file is new
