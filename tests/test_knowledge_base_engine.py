from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.knowledge_base import (
    KnowledgeBaseDatasetStatus,
    KnowledgeBaseEngine,
    KnowledgeBaseImportFormat,
    KnowledgeBaseRecordKind,
    KnowledgeBaseService,
    KnowledgeBaseWorker,
)
from engine.pipeline import PipelineJob, QueueType
from engine.repositories.review_repository import ReviewRepository
from engine.review.review_models import ReviewDecisionType


@pytest.fixture()
def knowledge_base_env() -> None:
    ReviewRepository.reset_state()


def _engine() -> KnowledgeBaseEngine:
    return KnowledgeBaseEngine()


def _build_bundle(*, dataset_id: int, name: str, character_series_id: int | None = 100) -> dict:
    return {
        "dataset": {
            "dataset_id": dataset_id,
            "name": name,
            "description": f"{name} dataset",
            "version": "2026.1",
            "status": KnowledgeBaseDatasetStatus.ACTIVE.value,
            "tags": ["trusted", "training"],
            "notes": "verified knowledge",
        },
        "series": [
            {
                "canonical_id": 100,
                "dataset_id": dataset_id,
                "title": "Seven Deadly Sins",
                "aliases": ["Nanatsu no Taizai"],
                "localized_titles": ["七つの大罪"],
                "description": "Fantasy series",
                "parent_series_id": None,
                "related_series_ids": [],
                "character_ids": [1542],
                "tags": ["anime"],
                "notes": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "characters": [
            {
                "canonical_id": 1542,
                "dataset_id": dataset_id,
                "series_id": character_series_id,
                "canonical_name": "Elizabeth",
                "aliases": ["Elizabeth Liones", "Liz"],
                "localized_names": ["エリザベス"],
                "romaji": "Erizabesu",
                "japanese": "エリザベス",
                "english": "Elizabeth",
                "gender": "female",
                "description": "Trusted canonical character",
                "reference_images": [],
                "approved_examples": [],
                "relationships": [],
                "tags": ["main"],
                "notes": "",
                "confidence_score": 0.72,
                "training_priority": 1.25,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "reference_images": [
            {
                "image_id": 5001,
                "character_id": 1542,
                "path": "reference/elizabeth_01.png",
                "quality_score": 0.96,
                "pose_type": "standing",
                "expression": "neutral",
                "outfit": "royal dress",
                "source": "curated",
                "approved": True,
                "embedding_id": 9001,
                "hash_id": 8001,
                "metadata": {"camera": "studio"},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "training_samples": [
            {
                "sample_id": 7001,
                "character_id": 1542,
                "image_id": 5001,
                "approved": True,
                "reviewed_by": "curator",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "confidence": 0.93,
                "source": "review",
                "weight": 1.2,
                "metadata": {"review_id": 1},
                "lora_metadata": {"pose": "standing"},
            }
        ],
    }


def test_dataset_creation_and_counts(knowledge_base_env: None) -> None:
    engine = _engine()
    dataset = engine.create_dataset(name="Anime", description="Trusted anime data", version="1.0")
    series = engine.create_series(dataset_id=dataset.dataset_id, canonical_id=100, title="Seven Deadly Sins", aliases=["Nanatsu no Taizai"])
    character = engine.create_character(
        dataset_id=dataset.dataset_id,
        canonical_id=1542,
        series_id=series.canonical_id,
        canonical_name="Elizabeth",
        aliases=["Elizabeth Liones", "Liz"],
        localized_names=["エリザベス"],
        romaji="Erizabesu",
        japanese="エリザベス",
        english="Elizabeth",
        tags=["main"],
    )
    reference = engine.add_reference_image(character_id=character.canonical_id, image_id=5001, path="reference/elizabeth_01.png", quality_score=0.98, source="curated")
    sample = engine.add_training_sample(character_id=character.canonical_id, image_id=5001, approved=True, reviewed_by="curator", reviewed_at=datetime.now(timezone.utc), confidence=0.95, source="review", weight=1.2)

    stored = engine.repository.find_dataset(dataset.dataset_id)
    assert stored is not None
    assert stored.series_count == 1
    assert stored.character_count == 1
    assert stored.reference_image_count == 1
    assert stored.training_sample_count == 1
    assert stored.image_count == 1
    assert reference.image_id == 5001
    assert sample.sample_id == 1

    exact = engine.lookup_by_alias("liz", dataset_id=dataset.dataset_id)
    assert exact
    assert exact[0].kind is KnowledgeBaseRecordKind.CHARACTER
    assert exact[0].record_id == 1542

    romaji = engine.lookup_by_romaji("erizabesu", dataset_id=dataset.dataset_id)
    assert romaji and romaji[0].record_id == 1542


def test_dataset_merge_moves_records(knowledge_base_env: None) -> None:
    engine = _engine()
    target = engine.create_dataset(name="Target", description="Primary dataset")
    source = engine.create_dataset(name="Source", description="Secondary dataset")

    engine.create_series(dataset_id=target.dataset_id, canonical_id=1, title="Target Series")
    engine.create_character(dataset_id=target.dataset_id, canonical_id=10, series_id=1, canonical_name="Target Hero")

    source_series = engine.create_series(dataset_id=source.dataset_id, canonical_id=2, title="Source Series")
    source_character = engine.create_character(dataset_id=source.dataset_id, canonical_id=20, series_id=source_series.canonical_id, canonical_name="Source Hero")

    merged = engine.merge_datasets(target.dataset_id, source.dataset_id)
    assert merged.dataset_id == target.dataset_id
    assert engine.repository.find_dataset(source.dataset_id) is None
    moved = engine.repository.find_character(source_character.canonical_id)
    assert moved is not None
    assert moved.dataset_id == target.dataset_id

    counts = engine.counts(target.dataset_id)
    assert counts["series"] == 2
    assert counts["characters"] == 2


def test_json_import_export_roundtrip(knowledge_base_env: None) -> None:
    engine = _engine()
    dataset = engine.create_dataset(name="Anime", description="Trusted anime data", version="2026.1")
    engine.create_series(dataset_id=dataset.dataset_id, canonical_id=100, title="Seven Deadly Sins", aliases=["Nanatsu no Taizai"])
    engine.create_character(dataset_id=dataset.dataset_id, canonical_id=1542, series_id=100, canonical_name="Elizabeth", aliases=["Liz"], localized_names=["エリザベス"], romaji="Erizabesu")

    exported = engine.export_dataset(dataset.dataset_id, format=KnowledgeBaseImportFormat.JSON)
    assert isinstance(exported, str)

    imported_engine = _engine()
    imported = imported_engine.import_dataset(exported, format=KnowledgeBaseImportFormat.JSON)
    assert imported.dataset_id == dataset.dataset_id
    assert imported_engine.counts(imported.dataset_id)["characters"] == 1
    assert imported_engine.lookup_by_character("Elizabeth")[0].record_id == 1542


def test_csv_import_export_roundtrip(knowledge_base_env: None) -> None:
    engine = _engine()
    dataset = engine.create_dataset(name="Games", description="Trusted game data", version="2026.1")
    engine.create_series(dataset_id=dataset.dataset_id, canonical_id=200, title="Fate", aliases=["Fate Series"])
    engine.create_character(dataset_id=dataset.dataset_id, canonical_id=300, series_id=200, canonical_name="Saber", aliases=["Artoria"], localized_names=["アルトリア"], romaji="Arutoria")

    exported = engine.export_dataset(dataset.dataset_id, format=KnowledgeBaseImportFormat.CSV)
    assert isinstance(exported, str)

    imported_engine = _engine()
    imported = imported_engine.import_dataset(exported, format=KnowledgeBaseImportFormat.CSV)
    assert imported.name == "Games"
    assert imported_engine.counts(imported.dataset_id)["series"] == 1
    assert imported_engine.lookup_by_alias("artoria")[0].record_id == 300


def test_validation_detects_common_issues(knowledge_base_env: None) -> None:
    engine = _engine()
    dataset = engine.create_dataset(name="Validation Base", description="Validation dataset")
    engine.create_series(dataset_id=dataset.dataset_id, canonical_id=10, title="Shared Series", aliases=["Shared"])
    engine.create_character(dataset_id=dataset.dataset_id, canonical_id=11, series_id=None, canonical_name="Orphan Character", aliases=["Shared"], tags=["main"])
    engine.create_dataset(name="Empty Dataset")

    imported_bundle = _build_bundle(dataset_id=3, name="Imported Validation", character_series_id=999)
    engine.import_bundle(imported_bundle, merge=False)

    report = engine.validate()
    assert report.valid is False
    assert report.duplicate_aliases >= 1
    assert report.missing_series >= 1
    assert report.orphan_characters >= 1
    assert report.orphan_series >= 1
    assert report.invalid_datasets == 0
    assert report.empty_datasets >= 1
    assert report.broken_references >= 1


def test_search_supports_fuzzy_case_insensitive_lookup(knowledge_base_env: None) -> None:
    engine = _engine()
    dataset = engine.create_dataset(name="Western Animation", description="Animation archive")
    engine.create_series(dataset_id=dataset.dataset_id, canonical_id=400, title="The Legend of Korra", aliases=["Korra"])
    engine.create_character(dataset_id=dataset.dataset_id, canonical_id=401, series_id=400, canonical_name="Korra", aliases=["Avatar Korra"], localized_names=["コーラ"], romaji="Kora", tags=["avatar"])

    exact = engine.lookup_candidates("kOrRa", dataset_id=dataset.dataset_id)
    assert exact
    assert exact[0].record_id == 401

    fuzzy = engine.lookup_candidates("legend kor", dataset_id=dataset.dataset_id)
    assert fuzzy
    assert fuzzy[0].kind in {KnowledgeBaseRecordKind.CHARACTER, KnowledgeBaseRecordKind.SERIES}
    assert fuzzy[0].score > 0.7

    by_tag = engine.search_tags("avatar", dataset_id=dataset.dataset_id)
    assert by_tag
    assert by_tag[0].record_id == 401

    by_dataset = engine.search_datasets("western")
    assert by_dataset
    assert by_dataset[0].record_id == dataset.dataset_id


def test_learning_integration_uses_review_samples(knowledge_base_env: None) -> None:
    engine = _engine()
    dataset = engine.create_dataset(name="Learning", description="Learning dataset")
    engine.create_series(dataset_id=dataset.dataset_id, canonical_id=500, title="Code Geass")
    engine.create_character(dataset_id=dataset.dataset_id, canonical_id=600, series_id=500, canonical_name="Lelouch", aliases=["Zero"], confidence_score=0.2)

    review_repo = ReviewRepository()
    review_item = review_repo.create_review_item(
        image_id=42,
        source_path=Path("c:/tmp/lelouch.png"),
        operation_type="recognition",
        confidence=0.88,
        proposed_value={"character_id": 600, "series_id": 500, "character_name": "Lelouch", "series_name": "Code Geass", "matched_alias": "Zero", "confidence": 0.88},
        current_value={"image_id": 42},
        series="Code Geass",
        character="Lelouch",
    )
    review_repo.apply_review_decision(review_item.review_id, decision=ReviewDecisionType.APPROVE, reviewer="tester", reason="confirmed")
    stored_review = review_repo.get_review_item(review_item.review_id)
    assert stored_review is not None
    assert stored_review.status.value == "approved"

    sample = engine.add_approved_review_sample(stored_review, dataset_id=dataset.dataset_id, character_id=600, weight=1.3)
    assert sample.approved is True
    assert sample.reviewed_by == "tester"
    character = engine.repository.find_character(600)
    assert character is not None
    assert character.approved_examples
    assert character.confidence_score > 0.2

    promoted = engine.promote_trusted_sample(sample.sample_id)
    assert promoted.approved is True
    rejected = engine.reject_training_sample(sample.sample_id)
    assert rejected.approved is False


def test_statistics_and_cache_rebuild(knowledge_base_env: None) -> None:
    engine = _engine()
    dataset = engine.create_dataset(name="Statistics", description="Statistics dataset")
    engine.create_series(dataset_id=dataset.dataset_id, canonical_id=700, title="Naruto", aliases=["NARUTO"])
    engine.create_character(dataset_id=dataset.dataset_id, canonical_id=701, series_id=700, canonical_name="Naruto", aliases=["Uzumaki Naruto"], tags=["ninja"])

    first = engine.lookup_candidates("naruto", dataset_id=dataset.dataset_id)
    second = engine.lookup_candidates("naruto", dataset_id=dataset.dataset_id)
    assert first and second

    snapshot = engine.statistics_snapshot()
    assert snapshot.searches >= 2
    assert snapshot.cache_hits >= 1
    assert snapshot.cache_misses >= 1

    rebuilt = engine.rebuild_statistics()
    assert rebuilt.datasets == 1
    assert rebuilt.characters == 1
    assert rebuilt.series == 1
    assert rebuilt.aliases >= 2


def test_worker_cancellation_and_resume(knowledge_base_env: None, tmp_path: Path) -> None:
    engine = _engine()
    service = KnowledgeBaseService(engine=engine)
    worker = KnowledgeBaseWorker(service=service)

    bundle = _build_bundle(dataset_id=9, name="Worker Dataset")
    job = PipelineJob(
        source_path=str(tmp_path / "knowledge.json"),
        queue_type=QueueType.SEARCH,
        metadata={
            "stage": "knowledge_base",
            "action": "import",
            "format": "json",
            "payload": bundle,
        },
    )

    worker.cancel(str(job.id))
    cancelled = worker.process_jobs([job])
    assert cancelled == []
    assert engine.counts()["datasets"] == 0

    worker.resume(str(job.id))
    resumed = worker.process_jobs([job])
    assert resumed
    assert engine.counts()["datasets"] == 1
    assert worker.is_cancelled(str(job.id)) is False
