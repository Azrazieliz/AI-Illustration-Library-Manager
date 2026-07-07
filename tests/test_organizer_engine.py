"""Tests for the Automatic Organizer Foundation (Commit 0025)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.organizer import OrganizationRule, OrganizerEngine
from engine.repositories.dataset_repository import DatasetRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.recognition_repository import RecognitionRepository


@pytest.fixture()
def organizer_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _register_image_for_organizer(
    path: Path,
    *,
    series: str | None = None,
    characters: list[str] | None = None,
    exif_data: dict[str, object] | None = None,
    provenance: list[str] | None = None,
) -> int:
    image_repo = ImageRepository()
    image = image_repo.create_image(
        original_path=str(path),
        filename=path.name,
        extension=path.suffix,
    )

    if series or characters:
        recognition_repo = RecognitionRepository()
        db_image = recognition_repo.get_image_by_path(str(path))
        assert db_image is not None
        recognition_repo.apply_recognition(
            image=db_image,
            series_name=series,
            character_names=characters or [],
        )

    if exif_data is not None:
        metadata_repo = MetadataRepository()
        metadata_repo.create_metadata_record(
            image_id=image.id,
            exif_data=json.dumps(exif_data),
        )

    if provenance:
        dataset_repo = DatasetRepository()
        dataset_repo.save_dataset_provenance(image.id, provenance)

    return image.id


def _default_rules() -> list[OrganizationRule]:
    return [
        OrganizationRule(
            name="primary",
            directory_template="{series}/{character}/{year}",
            priority=10,
            is_fallback=False,
            required_fields=("series",),
        ),
        OrganizationRule(
            name="fallback",
            directory_template="{unknown}/{first_letter}",
            priority=100,
            is_fallback=True,
        ),
    ]


def test_preview_mode(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "saber.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source, series="Fate", characters=["Saber"], exif_data={"Year": 2004})

    engine = OrganizerEngine(rules=_default_rules())
    plan = engine.preview_organize([source])

    assert len(plan.previews) == 1
    preview = plan.previews[0]
    assert preview.rule_name == "primary"
    assert "Fate" in preview.destination_path.parts
    assert "Saber" in preview.destination_path.parts
    assert "2004" in preview.destination_path.parts


def test_dry_run(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "dry.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source, series="Fate", characters=["Rin"])

    engine = OrganizerEngine(rules=_default_rules())
    result = engine.apply_organize([source], dry_run=True)

    assert result.dry_run is True
    assert result.applied is False
    assert source.exists()


def test_apply_and_directory_creation(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "apply.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source, series="Fate", characters=["Archer"], exif_data={"Year": 2005})

    engine = OrganizerEngine(rules=_default_rules())
    result = engine.apply_organize([source])

    assert result.applied is True
    destination = result.previews[0].destination_path
    assert destination.exists()
    assert destination.parent.exists()
    assert not source.exists()


def test_rollback(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "rollback.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source, series="Fate", characters=["Saber"], exif_data={"Year": 2004})

    engine = OrganizerEngine(rules=_default_rules())
    result = engine.apply_organize([source])
    destination = result.previews[0].destination_path

    rollback = engine.rollback_last_batch()

    assert rollback is not None
    assert rollback.rolled_back is True
    assert source.exists()
    assert not destination.exists()


def test_collision_handling(organizer_env: None, tmp_path: Path) -> None:
    src1 = tmp_path / "src1" / "same.png"
    src1.parent.mkdir(parents=True, exist_ok=True)
    src1.write_bytes(b"x")

    _register_image_for_organizer(src1, series="Fate", characters=["Saber"], exif_data={"Year": 2004})

    existing_destination = tmp_path / "src1" / "Fate" / "Saber" / "2004" / "same.png"
    existing_destination.parent.mkdir(parents=True, exist_ok=True)
    existing_destination.write_bytes(b"occupied")

    engine = OrganizerEngine(
        rules=[
            OrganizationRule(
                name="same",
                directory_template="{series}/{character}/{year}",
                priority=1,
                required_fields=("series",),
            )
        ]
    )
    plan = engine.preview_organize([src1])

    assert len(plan.previews) == 1
    assert plan.previews[0].conflicted is True
    assert plan.previews[0].destination_path.name == "same_001.png"


def test_existing_destination_conflict(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "existing.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source, series="Fate", characters=["Saber"], exif_data={"Year": 2004})

    existing_dir = tmp_path / "Fate" / "Saber" / "2004"
    existing_dir.mkdir(parents=True, exist_ok=True)
    (existing_dir / "existing.png").write_bytes(b"old")

    engine = OrganizerEngine(rules=_default_rules())
    plan = engine.preview_organize([source])

    preview = plan.previews[0]
    assert preview.conflicted is True
    assert preview.destination_path.name.startswith("existing_001")


def test_duplicate_move_detection(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "dup.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source, series="Fate", characters=["Saber"], exif_data={"Year": 2004})

    engine = OrganizerEngine(rules=_default_rules())
    plan = engine.preview_organize([source, source])

    assert len(plan.previews) == 2
    skipped = [preview for preview in plan.previews if preview.skipped]
    assert len(skipped) == 1
    assert skipped[0].reason == "Duplicate source in same batch"


def test_template_expansion_with_placeholders(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "expansion.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(
        source,
        series="Fate",
        characters=["Saber"],
        exif_data={"Year": 2004, "Source": "pixiv"},
    )

    rules = [
        OrganizationRule(
            name="expanded",
            directory_template="{series}/{character}/{source}/{year}/{first_letter}",
            priority=1,
            required_fields=("series",),
        )
    ]

    engine = OrganizerEngine(rules=rules)
    plan = engine.preview_organize([source])

    preview = plan.previews[0]
    assert "Fate" in preview.destination_path.parts
    assert "Saber" in preview.destination_path.parts
    assert "pixiv" in preview.destination_path.parts
    assert "2004" in preview.destination_path.parts
    assert "E" in preview.destination_path.parts


def test_windows_path_handling(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "windows_file.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source, series="Fate:Stay", characters=["Saber*"], exif_data={"Year": 2004})

    engine = OrganizerEngine(rules=_default_rules())
    plan = engine.preview_organize([source])

    preview = plan.previews[0]
    assert "Fate_Stay" in preview.destination_path.parts


def test_linux_path_handling(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "linux_file.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source, series="A/B", characters=["C\\D"], exif_data={"Year": 2012})

    engine = OrganizerEngine(rules=_default_rules())
    plan = engine.preview_organize([source])

    preview = plan.previews[0]
    assert "A_B" in preview.destination_path.parts
    assert "C_D" in preview.destination_path.parts


def test_missing_metadata_fallback_rule(organizer_env: None, tmp_path: Path) -> None:
    source = tmp_path / "missing.png"
    source.write_bytes(b"x")
    _register_image_for_organizer(source)

    engine = OrganizerEngine(rules=_default_rules())
    plan = engine.preview_organize([source])

    preview = plan.previews[0]
    assert preview.rule_name == "fallback"
    assert "unknown" in preview.destination_path.parts
