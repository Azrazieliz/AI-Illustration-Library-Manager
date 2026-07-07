from __future__ import annotations

from engine.character_database import (
    CharacterRelationship,
    CharacterDatabaseBuilder,
    CharacterDatabaseEngine,
    CharacterDatabaseService,
    CharacterDatabaseWorker,
    RelationshipType,
    WorkerJobStatus,
)
from engine.repositories.character_database_repository import CharacterDatabaseRepository


def _engine() -> CharacterDatabaseEngine:
    repository = CharacterDatabaseRepository(builder=CharacterDatabaseBuilder())
    return CharacterDatabaseEngine(repository=repository, builder=CharacterDatabaseBuilder())


def test_character_series_creation_and_lookup() -> None:
    engine = _engine()
    series = engine.create_series(series_id=10, canonical_title="Seven Deadly Sins", aliases=["Nanatsu no Taizai"])
    character = engine.create_character(
        character_id=1542,
        series_id=series.series_id,
        canonical_name="Elizabeth",
        aliases=["Elizabeth Liones", "Liz", "エリザベス"],
        japanese_name="エリザベス",
        english_name="Elizabeth",
        romaji="Erizabesu",
    )

    looked_up = engine.lookup_character(1542)
    by_alias = engine.resolve_alias("Liz")
    series_lookup = engine.series_for_character(1542)

    assert looked_up is not None
    assert looked_up.canonical_name == "Elizabeth"
    assert character.character_id == by_alias[0].character_id
    assert series_lookup is not None
    assert series_lookup.series_id == 10


def test_same_name_disambiguation_across_series() -> None:
    engine = _engine()
    s1 = engine.create_series(series_id=1, canonical_title="Seven Deadly Sins")
    s2 = engine.create_series(series_id=2, canonical_title="The Eminence in Shadow")

    _ = engine.create_character(character_id=1542, series_id=s1.series_id, canonical_name="Elizabeth", aliases=["エリザベス"])
    _ = engine.create_character(character_id=8427, series_id=s2.series_id, canonical_name="Elizabeth", aliases=["エリザベス"])

    rows = engine.disambiguate("Elizabeth")

    assert len(rows) == 2
    assert {item.series_title for item in rows} == {"Seven Deadly Sins", "The Eminence in Shadow"}


def test_search_partial_localized_and_fuzzy() -> None:
    engine = _engine()
    _ = engine.create_series(series_id=1, canonical_title="Code Geass")
    _ = engine.create_character(
        character_id=11,
        series_id=1,
        canonical_name="Lelouch",
        localized_names=["ルルーシュ"],
        aliases=["Zero"],
        romaji="Ruruushu",
    )

    partial = engine.search_characters("lel", fuzzy=False)
    localized = engine.search_characters("ルル", fuzzy=False)
    fuzzy = engine.search_characters("Lelush", fuzzy=True)

    assert len(partial) == 1
    assert len(localized) == 1
    assert len(fuzzy) == 1


def test_series_lookup_and_character_listing() -> None:
    engine = _engine()
    series = engine.create_series(series_id=5, canonical_title="Fate")
    _ = engine.create_character(character_id=100, series_id=5, canonical_name="Saber")
    _ = engine.create_character(character_id=101, series_id=5, canonical_name="Rin")

    rows = engine.characters_for_series(series.series_id)
    found = engine.lookup_series("Fate")

    assert len(rows) == 2
    assert found is not None
    assert found.series_id == 5


def test_relationship_graph_validation_and_broken_references() -> None:
    engine = _engine()
    _ = engine.create_series(series_id=7, canonical_title="Family")
    _ = engine.create_character(character_id=1, series_id=7, canonical_name="Parent")
    _ = engine.create_character(character_id=2, series_id=7, canonical_name="Child")

    repo = engine.repository
    parent = repo.find_character(1)
    child = repo.find_character(2)
    assert parent is not None and child is not None
    parent.relationships = [CharacterRelationship(1, 2, RelationshipType.PARENT)]
    child.relationships = [CharacterRelationship(2, 1, RelationshipType.PARENT)]
    repo._characters[1] = parent
    repo._characters[2] = child

    report = engine.validate_database()

    assert report.circular_relationship_graphs > 0
    assert report.valid is False


def test_duplicate_canonical_name_within_series_validation() -> None:
    engine = _engine()
    _ = engine.create_series(series_id=42, canonical_title="Duplicate Realm")
    _ = engine.create_character(character_id=200, series_id=42, canonical_name="Alice")
    _ = engine.create_character(character_id=201, series_id=42, canonical_name="Alice")

    report = engine.validate_database()

    assert report.duplicate_canonical_names_in_series == 1
    assert report.valid is False


def test_merge_character_and_series() -> None:
    engine = _engine()
    _ = engine.create_series(series_id=1, canonical_title="Old")
    _ = engine.create_series(series_id=2, canonical_title="New")
    _ = engine.create_character(character_id=1, series_id=1, canonical_name="Alpha", aliases=["A"])
    _ = engine.create_character(character_id=2, series_id=2, canonical_name="Beta", aliases=["B"])

    merged_character = engine.merge_character(1, 2)
    merged_series = engine.merge_series(1, 2)

    assert merged_character.character_id == 2
    assert "A" in merged_character.aliases
    assert merged_series.series_id == 2


def test_import_merge_database_and_statistics() -> None:
    engine = _engine()
    merge_result = engine.merge_database(
        {
            "series": [
                {"series_id": 501, "canonical_title": "Steins;Gate", "aliases": ["シュタインズ・ゲート"]},
            ],
            "characters": [
                {"character_id": 9001, "series_id": 501, "canonical_name": "Kurisu", "aliases": ["Christina"]},
            ],
        }
    )

    assert len(merge_result["series"]) == 1
    assert len(merge_result["characters"]) == 1
    assert engine.statistics.imports >= 2
    assert engine.statistics.validation_runs >= 1


def test_service_repository_and_worker_flows() -> None:
    engine = _engine()
    service = CharacterDatabaseService(engine=engine)
    worker = CharacterDatabaseWorker(service=service)
    worker.start()

    import_series_job = worker.submit_import_series([
        {"series_id": 1000, "canonical_title": "Test Series"},
    ])
    import_char_job = worker.submit_import_characters([
        {"character_id": 1001, "series_id": 1000, "canonical_name": "Tester", "aliases": ["T"]},
    ])
    validation_job = worker.submit_validation()

    worker._queue.join()
    series_result = worker.result_for(import_series_job)
    char_result = worker.result_for(import_char_job)
    validation_result = worker.result_for(validation_job)

    assert len(series_result) == 1
    assert len(char_result) == 1
    assert validation_result.valid is True
    assert worker.job_for(validation_job) is not None
    assert worker.job_for(validation_job).status in {WorkerJobStatus.COMPLETED, WorkerJobStatus.CANCELLED}

    worker.stop()
