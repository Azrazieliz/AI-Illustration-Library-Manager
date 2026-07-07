"""Tests for the Recognition Engine (Commit 0014)."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.recognition import (
    RecognitionLabel,
    MockRecognitionProvider,
    RecognitionCheckpoint,
    RecognitionEngine,
    RecognitionOutput,
    RecognitionResult,
    RecognitionService,
    aggregate_recognition_results,
    rank_character_candidates,
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


def test_rank_character_candidates_deduplicates_and_ranks() -> None:
    labels = [
        RecognitionLabel(name="Saber", confidence=0.75),
        RecognitionLabel(name="Rin", confidence=0.82),
        RecognitionLabel(name="Saber", confidence=0.81),
    ]

    ranked = rank_character_candidates(labels)

    assert [candidate.name for candidate in ranked] == ["Rin", "Saber"]
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2
    assert ranked[1].occurrences == 2
    assert ranked[1].confidence > 0.81


def test_recognition_output_calculates_overall_confidence() -> None:
    output = RecognitionOutput(
        series=RecognitionLabel(name="Fate", confidence=0.9),
        characters=[
            RecognitionLabel(name="Saber", confidence=0.8),
            RecognitionLabel(name="Rin", confidence=0.7),
        ],
        provider_name="mock",
        model_name="mock-recognition",
        model_version="1.0.0",
    )

    assert output.overall_confidence is not None
    assert output.overall_confidence == 0.8
    assert [candidate.rank for candidate in output.character_candidates] == [1, 2]


def test_aggregate_recognition_results_returns_summary(tmp_path: Path) -> None:
    path1 = tmp_path / "fate__saber.png"
    path2 = tmp_path / "fate__rin.png"

    result1 = RecognitionResult(
        image_id=1,
        path=path1,
        output=RecognitionOutput(
            series=RecognitionLabel(name="Fate", confidence=0.9),
            characters=[RecognitionLabel(name="Saber", confidence=0.8)],
        ),
    )
    result2 = RecognitionResult(
        image_id=2,
        path=path2,
        output=RecognitionOutput(
            series=RecognitionLabel(name="Fate", confidence=0.7),
            characters=[RecognitionLabel(name="Rin", confidence=0.6)],
        ),
    )

    aggregation = aggregate_recognition_results([result1, result2])

    assert aggregation.total_results == 2
    assert aggregation.recognized_series_count == 2
    assert aggregation.recognized_character_count == 2
    assert aggregation.top_series[0] == ("Fate", 2)
    assert aggregation.average_series_confidence == 0.8


def test_engine_process_path_uses_cache(recognition_env: None, tmp_path: Path) -> None:
    img_path = tmp_path / "honkai__kiana+mei.jpg"
    img_path.write_bytes(b"fake")
    _register_image(img_path)

    provider = MockRecognitionProvider()
    provider.initialize()
    engine = RecognitionEngine(provider=provider)

    first = engine.process_path(img_path)
    second = engine.process_path(img_path)

    assert first is not None
    assert second is not None
    assert engine.statistics.cache_hits >= 1
    assert engine.statistics.average_confidence is not None


def test_service_review_metadata_contains_candidates(recognition_env: None, tmp_path: Path) -> None:
    img_path = tmp_path / "rezero__rem+ram.jpg"
    img_path.write_bytes(b"fake")
    _register_image(img_path)

    queue_manager = QueueManager()
    service = RecognitionService(queue_manager=queue_manager)
    job = PipelineJob(source_path=str(img_path), queue_type=QueueType.RECOGNITION)

    result = service.process_recognition_job(job)

    assert result is not None
    review_job = queue_manager.dequeue(QueueType.REVIEW)
    assert review_job is not None
    assert "character_candidates" in review_job.metadata
    assert len(review_job.metadata["character_candidates"]) == 2
    assert review_job.metadata["overall_confidence"] is not None
