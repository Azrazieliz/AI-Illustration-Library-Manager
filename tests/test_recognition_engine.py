"""Tests for the Recognition Engine (Commit 0014)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import (
    MockRecognitionProvider,
    RecognitionCheckpoint,
    RecognitionEngine,
    RecognitionService,
)
from engine.repositories.image_repository import ImageRepository
from engine.repositories.recognition_repository import RecognitionRepository


@pytest.fixture()
def recognition_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_mock_provider_parses_filename(recognition_env: None, tmp_path: Path) -> None:
    provider = MockRecognitionProvider()
    provider.initialize()

    path = tmp_path / "fate_stay_night__saber+rin.png"
    path.write_bytes(b"fake")

    output = provider.recognize(path)

    assert output.series is not None
    assert output.series.name == "Fate Stay Night"
    assert [c.name for c in output.characters] == ["Saber", "Rin"]
    assert output.provider_name == "mock"


def test_engine_process_single_path(recognition_env: None, tmp_path: Path) -> None:
    img_path = tmp_path / "bleach__rukia+ichigo.jpg"
    img_path.write_bytes(b"fake")
    image_id = _register_image(img_path)

    provider = MockRecognitionProvider()
    provider.initialize()
    engine = RecognitionEngine(provider=provider)

    result = engine.process_path(img_path)

    assert result is not None
    assert result.image_id == image_id
    assert result.output.series is not None
    assert result.output.series.name == "Bleach"
    assert [c.name for c in result.output.characters] == ["Rukia", "Ichigo"]

    repo = RecognitionRepository()
    image = repo.get_image_by_path(str(img_path))
    assert image is not None
    assert image.series is not None
    assert image.series.name == "Bleach"
    assert sorted(character.name for character in image.characters) == ["Ichigo", "Rukia"]


def test_engine_checkpoint_skips_processed(recognition_env: None, tmp_path: Path) -> None:
    img_path = tmp_path / "naruto__naruto.jpg"
    img_path.write_bytes(b"fake")
    _register_image(img_path)

    provider = MockRecognitionProvider()
    provider.initialize()
    engine = RecognitionEngine(provider=provider)

    checkpoint = RecognitionCheckpoint()
    checkpoint.add_processed(str(img_path.resolve()))

    result = engine.process_path(img_path, checkpoint=checkpoint)

    assert result is None


def test_engine_missing_image_record(recognition_env: None, tmp_path: Path) -> None:
    img_path = tmp_path / "no_record__character.jpg"
    img_path.write_bytes(b"fake")

    provider = MockRecognitionProvider()
    provider.initialize()
    engine = RecognitionEngine(provider=provider)

    result = engine.process_path(img_path)

    assert result is None


def test_service_publishes_review_job(recognition_env: None, tmp_path: Path) -> None:
    img_path = tmp_path / "one_piece__luffy+zoro.jpg"
    img_path.write_bytes(b"fake")
    image_id = _register_image(img_path)

    queue_manager = QueueManager()
    service = RecognitionService(queue_manager=queue_manager)

    job = PipelineJob(source_path=str(img_path), queue_type=QueueType.RECOGNITION)
    result = service.process_recognition_job(job)

    assert result is not None
    assert result.image_id == image_id

    review_job = queue_manager.dequeue(QueueType.REVIEW)
    assert review_job is not None
    assert review_job.metadata["review_type"] == "recognition"
    assert review_job.metadata["series"] == "One Piece"
    assert [item["name"] for item in review_job.metadata["characters"]] == ["Luffy", "Zoro"]


def test_service_skips_job_without_source_path(recognition_env: None) -> None:
    queue_manager = QueueManager()
    service = RecognitionService(queue_manager=queue_manager)

    job = PipelineJob(queue_type=QueueType.RECOGNITION)
    result = service.process_recognition_job(job)

    assert result is None
