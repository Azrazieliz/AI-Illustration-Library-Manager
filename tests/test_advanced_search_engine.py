from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.repositories.advanced_search_repository import AdvancedSearchRepository
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.recognition_repository import RecognitionRepository
from engine.repositories.review_repository import ReviewRepository
from engine.repositories.tagging_repository import TaggingRepository
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.review.review_models import ReviewDecisionType
from engine.search_advanced import (
    AdvancedSearchBatchItem,
    AdvancedSearchCheckpoint,
    AdvancedSearchEngine,
    AdvancedSearchQuery,
    AdvancedSearchService,
    AdvancedSearchWorker,
    AdvancedSortBy,
    AdvancedSortDirection,
)


@pytest.fixture()
def advanced_search_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
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

    return _seed_dataset(tmp_path)


def _seed_dataset(tmp_path: Path) -> dict[str, int]:
    image_repo = ImageRepository()
    metadata_repo = MetadataRepository()
    embedding_repo = EmbeddingRepository()
    review_repo = ReviewRepository()
    duplicate_repo = DuplicateRepository()

    paths = [
        tmp_path / "fate" / "saber" / "saber_pose_01.png",
        tmp_path / "fate" / "rin" / "rin_cast_01.jpg",
        tmp_path / "naruto" / "uzumaki" / "naruto_run_01.webp",
        tmp_path / "misc" / "landscape" / "sunset_scene.tif",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"img")

    image_ids: list[int] = []
    for path in paths:
        image = image_repo.create_image(original_path=str(path), filename=path.name, extension=path.suffix)
        image_repo.update_image(
            image,
            width={".png": 1200, ".jpg": 900, ".webp": 800, ".tif": 2000}[path.suffix],
            height={".png": 1600, ".jpg": 1400, ".webp": 1000, ".tif": 1200}[path.suffix],
            modified_date=datetime.now(timezone.utc) - timedelta(days=len(image_ids)),
            scan_date=datetime.now(timezone.utc) - timedelta(days=len(image_ids) + 1),
        )
        image_ids.append(image.id)

    # metadata
    metadata_repo.create_metadata_record(
        image_id=image_ids[0],
        mime_type="image/png",
        color_mode="RGBA",
        orientation="normal",
        is_animated=False,
        exif_data="saber pose golden hour",
    )
    metadata_repo.create_metadata_record(
        image_id=image_ids[1],
        mime_type="image/jpeg",
        color_mode="RGB",
        orientation="normal",
        is_animated=False,
        exif_data="mage casting scene",
    )
    metadata_repo.create_metadata_record(
        image_id=image_ids[2],
        mime_type="image/webp",
        color_mode="RGB",
        orientation="normal",
        is_animated=True,
        exif_data="ninja running action",
    )
    metadata_repo.create_metadata_record(
        image_id=image_ids[3],
        mime_type="image/tiff",
        color_mode="RGB",
        orientation="normal",
        is_animated=False,
        exif_data="sunset mountain",
    )

    # embeddings
    embedding_repo.create_embedding_record(image_id=image_ids[0], vector_path="vector:saber", model_name="mock", model_version="1")
    embedding_repo.create_embedding_record(image_id=image_ids[1], vector_path="vector:rin", model_name="mock", model_version="1")
    embedding_repo.create_embedding_record(image_id=image_ids[2], vector_path="vector:naruto", model_name="mock", model_version="1")
    embedding_repo.create_embedding_record(image_id=image_ids[3], vector_path="vector:sunset", model_name="mock", model_version="1")
    embedding_repo.commit()

    # series + characters via recognition repository
    rec_repo = RecognitionRepository()
    first = rec_repo.get_image_by_path(str(paths[0]))
    second = rec_repo.get_image_by_path(str(paths[1]))
    third = rec_repo.get_image_by_path(str(paths[2]))
    assert first is not None and second is not None and third is not None
    rec_repo.apply_recognition(image=first, series_name="Fate", character_names=["Saber"])
    rec_repo.apply_recognition(image=second, series_name="Fate", character_names=["Rin"])
    rec_repo.apply_recognition(image=third, series_name="Naruto", character_names=["Naruto"])

    # tags
    tag_repo = TaggingRepository()
    i1 = tag_repo.get_image_by_path(str(paths[0]))
    i2 = tag_repo.get_image_by_path(str(paths[1]))
    i3 = tag_repo.get_image_by_path(str(paths[2]))
    i4 = tag_repo.get_image_by_path(str(paths[3]))
    assert i1 is not None and i2 is not None and i3 is not None and i4 is not None

    def add_tag(image, name: str, category: str = "general") -> None:
        tag = tag_repo.get_or_create_tag(name=name, category=category)
        tag_repo.assign_tag(image, tag)

    add_tag(i1, "heroine")
    add_tag(i1, "knight")
    add_tag(i2, "mage")
    add_tag(i2, "heroine")
    add_tag(i3, "hero")
    add_tag(i3, "ninja")
    add_tag(i4, "landscape")
    tag_repo.commit_changes()

    # review statuses
    r1 = review_repo.create_review_item(
        image_id=image_ids[0],
        source_path=paths[0],
        operation_type="recognition",
        confidence=0.95,
        proposed_value={"series": "Fate", "character": "Saber"},
        current_value={"series": None},
        series="Fate",
        character="Saber",
    )
    review_repo.apply_review_decision(r1.review_id, decision=ReviewDecisionType.APPROVE, reviewer="qa")

    _ = review_repo.create_review_item(
        image_id=image_ids[1],
        source_path=paths[1],
        operation_type="recognition",
        confidence=0.6,
        proposed_value={"series": "Fate", "character": "Rin"},
        current_value={"series": None},
        series="Fate",
        character="Rin",
    )

    r3 = review_repo.create_review_item(
        image_id=image_ids[2],
        source_path=paths[2],
        operation_type="recognition",
        confidence=0.2,
        proposed_value={"series": "Naruto", "character": "Naruto"},
        current_value={"series": None},
        series="Naruto",
        character="Naruto",
    )
    review_repo.apply_review_decision(r3.review_id, decision=ReviewDecisionType.REJECT, reviewer="qa")

    # duplicates
    _ = duplicate_repo.create_duplicate(
        image_a_id=image_ids[0],
        image_b_id=image_ids[1],
        match_type="perceptual",
        confidence="medium",
        sha256_match=False,
        phash_distance=10,
        ahash_distance=12,
        dhash_distance=11,
        overall_score=0.82,
        status="pending",
    )

    return {
        "saber": image_ids[0],
        "rin": image_ids[1],
        "naruto": image_ids[2],
        "landscape": image_ids[3],
    }


def _engine() -> AdvancedSearchEngine:
    return AdvancedSearchEngine(repository=AdvancedSearchRepository())


def test_boolean_parser_and_nested_logic(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    ast = engine.builder.parse_query("(series:fate AND tag:heroine) OR (character:naruto AND NOT tag:villain)")
    assert ast is not None

    response = engine.search(
        AdvancedSearchQuery(query_text="(series:fate AND tag:heroine) OR (character:naruto AND NOT tag:villain)")
    )
    ids = {item.image_id for item in response.results}
    assert advanced_search_env["saber"] in ids
    assert advanced_search_env["rin"] in ids
    assert advanced_search_env["naruto"] in ids


def test_phrase_exact_partial_and_fuzzy_queries(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()

    phrase = engine.search(AdvancedSearchQuery(query_text='"saber pose"'))
    assert phrase.results
    assert phrase.results[0].image_id == advanced_search_env["saber"]

    exact = engine.search(AdvancedSearchQuery(query_text="character:=saber"))
    assert exact.results
    assert exact.results[0].image_id == advanced_search_env["saber"]

    partial = engine.search(AdvancedSearchQuery(query_text="sab"))
    assert partial.results
    assert partial.results[0].image_id == advanced_search_env["saber"]

    fuzzy = engine.search(AdvancedSearchQuery(query_text="character:sabr~"))
    assert fuzzy.results
    assert fuzzy.results[0].image_id == advanced_search_env["saber"]


def test_hybrid_ranking_and_explanations(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    query = AdvancedSearchQuery(query_text="saber heroine", semantic_query="vector:saber", include_explanations=True)
    response = engine.search(query)

    assert response.results
    top = response.results[0]
    assert top.image_id == advanced_search_env["saber"]
    assert top.explanation is not None
    assert top.explanation.total_score >= 0.5


def test_filtering_review_duplicate_rating_resolution_file_date_folder_path(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    query = AdvancedSearchQuery(
        query_text="fate",
        filters=engine.builder.query_from_payload(
            {
                "filters": {
                    "review_statuses": ["approved"],
                    "include_duplicates": True,
                    "min_rating": 0.9,
                    "min_width": 1000,
                    "file_types": ["png"],
                    "folder_contains": "fate/saber",
                    "path_contains": "saber_pose",
                }
            }
        ).filters,
    )

    response = engine.search(query)
    assert len(response.results) == 1
    assert response.results[0].image_id == advanced_search_env["saber"]


def test_pagination_and_sorting(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    response = engine.search(
        AdvancedSearchQuery(
            query_text="",
            sort_by=AdvancedSortBy.FILENAME,
            sort_direction=AdvancedSortDirection.ASC,
            page=2,
            page_size=2,
        )
    )
    assert response.total == 4
    assert response.page == 2
    assert len(response.results) == 2
    assert response.results[0].filename <= response.results[1].filename


def test_faceted_search(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    response = engine.search(AdvancedSearchQuery(query_text="fate OR naruto", include_facets=True))
    assert response.facets is not None
    assert any(bucket.value == "heroine" for bucket in response.facets.tags)
    assert any(bucket.value == "Fate" for bucket in response.facets.series)


def test_collection_search_and_filter(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()

    by_query = engine.search(AdvancedSearchQuery(query_text="collection:fate"))
    assert by_query.results
    ids = {item.image_id for item in by_query.results}
    assert advanced_search_env["saber"] in ids
    assert advanced_search_env["rin"] in ids

    filtered = engine.search(
        AdvancedSearchQuery(
            query_text="",
            filters=engine.builder.query_from_payload({"filters": {"collections": ["naruto"]}}).filters,
        )
    )
    assert filtered.total == 1
    assert filtered.results[0].image_id == advanced_search_env["naruto"]


def test_saved_searches_and_history(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    query = AdvancedSearchQuery(query_text="tag:heroine")
    saved = engine.save_search(name="heroine lookup", query=query)
    replay = engine.run_saved_search(saved.search_id)

    assert replay is not None
    assert replay.results
    assert len(engine.list_saved_searches()) == 1
    assert len(engine.history()) >= 1


def test_query_cache_and_invalidation(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    query = AdvancedSearchQuery(query_text="naruto", use_cache=True)

    first = engine.search(query)
    second = engine.search(query)

    assert first.total == second.total
    assert engine.statistics.cache_misses >= 1
    assert engine.statistics.cache_hits >= 1

    engine.invalidate_cache()
    _ = engine.search(query)
    assert engine.statistics.cache_misses >= 2


def test_preview_mode(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    response = engine.search(AdvancedSearchQuery(query_text="fate", preview_mode=True))
    assert response.results
    assert "resolution" in response.results[0].preview


def test_batch_search_and_resume_checkpoint(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    checkpoint = AdvancedSearchCheckpoint()
    checkpoint.add_processed_batch_item("one")

    batch = [
        AdvancedSearchBatchItem(batch_item_id="one", query=AdvancedSearchQuery(query_text="saber")),
        AdvancedSearchBatchItem(batch_item_id="two", query=AdvancedSearchQuery(query_text="naruto")),
    ]

    response = engine.batch_search(batch, checkpoint=checkpoint)
    assert len(response.responses) == 1
    assert response.responses[0].query_id == "two"


def test_worker_cancellation_and_resume(advanced_search_env: dict[str, int]) -> None:
    queue_manager = QueueManager()
    engine = _engine()
    service = AdvancedSearchService(queue_manager=queue_manager, engine=engine)
    worker = AdvancedSearchWorker(queue_manager=queue_manager, service=service)

    job = PipelineJob(
        source_path="",
        queue_type=QueueType.SEARCH,
        metadata={
            "stage": "advanced_search",
            "action": "search",
            "query": {"query_text": "saber"},
        },
    )

    worker.cancel(str(job.id))
    cancelled = worker.process_jobs([job])
    assert cancelled == []

    worker.resume(str(job.id))
    resumed = worker.process_jobs([job])
    assert len(resumed) == 1
    assert resumed[0].success is True


def test_statistics_collection(advanced_search_env: dict[str, int]) -> None:
    engine = _engine()
    engine.statistics.start()
    _ = engine.search(AdvancedSearchQuery(query_text="saber"))
    _ = engine.search(AdvancedSearchQuery(query_text="saber"))
    _ = engine.batch_search([AdvancedSearchBatchItem(batch_item_id="batch-1", query=AdvancedSearchQuery(query_text="rin"))])
    engine.statistics.finish()

    assert engine.statistics.searches >= 2
    assert engine.statistics.batch_searches >= 1
    assert engine.statistics.documents_scanned >= 1
