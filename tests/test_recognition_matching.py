from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.pipeline import PipelineJob, QueueType
from engine.recognition import MockRecognitionProvider, RecognitionEngine, RecognitionService
from engine.recognition.recognition_models import RecognitionCheckpoint
from engine.repositories.image_repository import ImageRepository
from engine.repositories.review_repository import ReviewRepository
from engine.review.review_models import ReviewDecisionType


@pytest.fixture()
def recognition_matching_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    ReviewRepository.reset_state()


def _register_image(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")
    repo = ImageRepository()
    image = repo.create_image(original_path=str(path.resolve()), filename=path.name, extension=path.suffix)
    return image.id


def _engine() -> RecognitionEngine:
    provider = MockRecognitionProvider()
    provider.initialize()
    return RecognitionEngine(provider=provider)


def test_exact_alias_matching_and_auto_assignment(recognition_matching_env: None, tmp_path: Path) -> None:
    engine = _engine()
    db = engine.character_database_repository
    series = db.create_series(series_id=100, canonical_title="Seven Deadly Sins", aliases=["Nanatsu no Taizai"])
    _ = db.create_character(
        character_id=1542,
        series_id=series.series_id,
        canonical_name="Elizabeth",
        aliases=["Elizabeth Liones", "Liz", "エリザベス"],
        japanese_name="エリザベス",
        english_name="Elizabeth",
        romaji="Erizabesu",
    )

    path = tmp_path / "Seven Deadly Sins" / "seven_deadly_sins__Elizabeth_Liones.png"
    _register_image(path)

    result = engine.process_path(path)

    assert result is not None
    assert result.auto_assigned is True
    assert result.assignment is not None
    assert result.assignment.character_id == 1542
    assert result.assignment.series_id == 100
    assert result.assignment.character_name == "Elizabeth"
    assert result.output.assigned_character_id == 1542
    assert result.output.assigned_series_id == 100


def test_same_name_disambiguation_uses_series_hint(recognition_matching_env: None, tmp_path: Path) -> None:
    engine = _engine()
    db = engine.character_database_repository
    sds = db.create_series(series_id=1, canonical_title="Seven Deadly Sins", aliases=["Nanatsu no Taizai"])
    eminence = db.create_series(series_id=2, canonical_title="The Eminence in Shadow", aliases=["Eminence in Shadow"])
    _ = db.create_character(character_id=1542, series_id=sds.series_id, canonical_name="Elizabeth", aliases=["エリザベス"])
    _ = db.create_character(character_id=8427, series_id=eminence.series_id, canonical_name="Elizabeth", aliases=["エリザベス"])

    path = tmp_path / "The Eminence in Shadow" / "unknown__Elizabeth.png"
    _register_image(path)

    result = engine.process_path(path)

    assert result is not None
    assert result.assignment is not None
    assert result.assignment.character_id == 8427
    assert result.assignment.series_id == 2
    assert result.matched_candidates[0].character_id == 8427
    assert result.matched_candidates[0].rank == 1


def test_unknown_character_creates_review_entry(recognition_matching_env: None, tmp_path: Path) -> None:
    engine = _engine()
    _ = engine.character_database_repository.create_series(series_id=50, canonical_title="Known Series")

    path = tmp_path / "known_series__completely_unknown.png"
    _register_image(path)

    result = engine.process_path(path)

    assert result is not None
    assert result.auto_assigned is False
    assert result.needs_review is True
    assert result.review_item_id is not None
    review_items = engine.recognition_repository.review_repository.list_review_items()
    assert len(review_items) == 1
    assert review_items[0].proposed_value["character_id"] is None
    assert review_items[0].status.value == "pending"


def test_learning_increases_confidence_after_approval(recognition_matching_env: None, tmp_path: Path) -> None:
    engine = _engine()
    db = engine.character_database_repository
    s1 = db.create_series(series_id=1, canonical_title="Seven Deadly Sins")
    s2 = db.create_series(series_id=2, canonical_title="The Eminence in Shadow")
    _ = db.create_character(character_id=1542, series_id=s1.series_id, canonical_name="Elizabeth")
    _ = db.create_character(character_id=8427, series_id=s2.series_id, canonical_name="Elizabeth")

    path = tmp_path / "unknown__Elizabeth.png"
    _register_image(path)

    first = engine.process_path(path)
    assert first is not None
    assert first.assignment is not None
    assert first.needs_review is True
    review_item_id = first.review_item_id
    assert review_item_id is not None

    engine.recognition_repository.review_repository.apply_review_decision(
        review_item_id,
        decision=ReviewDecisionType.APPROVE,
        reviewer="tester",
        reason="Confirmed correct Elizabeth",
    )

    second = engine.process_path(path)
    assert second is not None
    assert second.assignment is not None
    assert second.assignment.confidence > first.assignment.confidence


def test_cache_behavior_and_statistics(recognition_matching_env: None, tmp_path: Path) -> None:
    engine = _engine()
    db = engine.character_database_repository
    series = db.create_series(series_id=11, canonical_title="Code Geass")
    _ = db.create_character(character_id=99, series_id=series.series_id, canonical_name="Lelouch", aliases=["Zero"])

    path = tmp_path / "code_geass__Zero.png"
    _register_image(path)

    first = engine.process_path(path)
    second = engine.process_path(path)

    assert first is not None
    assert second is not None
    assert engine.statistics.cache_hits >= 1
    assert engine.statistics.average_confidence is not None
    assert engine.statistics.matching_time_seconds >= 0.0
    assert engine.statistics.ranking_time_seconds >= 0.0


def test_service_metadata_contains_canonical_assignment(recognition_matching_env: None, tmp_path: Path) -> None:
    engine = _engine()
    db = engine.character_database_repository
    series = db.create_series(series_id=21, canonical_title="Fate")
    _ = db.create_character(character_id=1, series_id=series.series_id, canonical_name="Saber", aliases=["Artoria"])

    path = tmp_path / "fate__Artoria.png"
    _register_image(path)

    service = RecognitionService(engine=engine)
    result = service.process_recognition_job(
        PipelineJob(source_path=str(path), queue_type=QueueType.RECOGNITION)
    )

    assert result is not None
    review_job = service.queue_manager.dequeue(QueueType.REVIEW)
    assert review_job is not None
    assert review_job.metadata["canonical_assignment"]["character_id"] == 1
    assert review_job.metadata["assigned_character_id"] == 1
    assert review_job.metadata["candidate_payloads"][0]["character_name"] == "Saber"


def test_checkpoint_skips_processed_path(recognition_matching_env: None, tmp_path: Path) -> None:
    engine = _engine()
    db = engine.character_database_repository
    series = db.create_series(series_id=33, canonical_title="Naruto")
    _ = db.create_character(character_id=33, series_id=series.series_id, canonical_name="Naruto")

    path = tmp_path / "naruto__naruto.png"
    _register_image(path)

    checkpoint = RecognitionCheckpoint()
    checkpoint.add_processed(str(path.resolve()))

    result = engine.process_path(path, checkpoint=checkpoint)

    assert result is None
