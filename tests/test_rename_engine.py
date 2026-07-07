"""Tests for the Automatic Rename Foundation (Commit 0024)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.rename import RenameEngine, RenameRule, RenameTemplate, build_safe_filename, sanitize_stem
from engine.repositories.dataset_repository import DatasetRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.recognition_repository import RecognitionRepository


@pytest.fixture()
def rename_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _register_image_with_metadata(
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


def test_template_expansion_uses_defaults_and_index() -> None:
    template = RenameTemplate("{series}_{character}_{variant}_{artist_guess}_{source}_{index}_{year}")
    rule = RenameRule(
        unknown_defaults={
            "series": "s_unknown",
            "character": "c_unknown",
            "variant": "v_unknown",
            "artist_guess": "a_unknown",
            "source": "src_unknown",
            "index": "000",
            "year": "0000",
        }
    )

    from engine.rename.rename_models import RenameContext

    context = RenameContext(
        image_id=1,
        source_path=Path("/tmp/example.png"),
        extension=".png",
        values={"series": "Fate", "character": "Saber"},
    )

    value = template.expand(context, rule, sequence=7)

    assert value == "Fate_Saber_v_unknown_a_unknown_src_unknown_007_0000"


def test_sanitization_and_extension_preservation() -> None:
    assert sanitize_stem("  many___   spaces   ") == "many_ spaces"
    assert sanitize_stem("CON") == "CON_file"
    built = build_safe_filename("bad:name*with?chars", ".jpg")
    assert built.endswith(".jpg")
    assert re.search(r"[<>:\"/\\|?*]", built) is None


def test_preview_generates_defaults_when_metadata_missing(rename_env: None, tmp_path: Path) -> None:
    source = tmp_path / "source image.png"
    source.write_bytes(b"x")
    _register_image_with_metadata(source)

    engine = RenameEngine()
    previews = engine.preview_rename([source], rule=RenameRule(template="{series}_{character}_{index}"))

    assert len(previews) == 1
    assert previews[0].target_path.suffix == ".png"
    assert "unknown_series" in previews[0].target_path.stem
    assert "unknown_character" in previews[0].target_path.stem


def test_duplicate_target_filenames_are_numbered(rename_env: None, tmp_path: Path) -> None:
    p1 = tmp_path / "a.jpg"
    p2 = tmp_path / "b.jpg"
    p1.write_bytes(b"1")
    p2.write_bytes(b"2")

    _register_image_with_metadata(p1, series="Fate", characters=["Saber"])
    _register_image_with_metadata(p2, series="Fate", characters=["Saber"])

    engine = RenameEngine()
    previews = engine.preview_rename([p1, p2], rule=RenameRule(template="{series}_{character}"))

    targets = [preview.target_path.name for preview in previews]
    assert len(set(targets)) == 2
    assert any(name.startswith("Fate_Saber_001") for name in targets)


def test_existing_target_conflict_is_numbered(rename_env: None, tmp_path: Path) -> None:
    existing = tmp_path / "Fate_Saber.jpg"
    existing.write_bytes(b"existing")

    source = tmp_path / "incoming.jpg"
    source.write_bytes(b"x")
    _register_image_with_metadata(source, series="Fate", characters=["Saber"])

    engine = RenameEngine()
    previews = engine.preview_rename([source], rule=RenameRule(template="{series}_{character}"))

    assert len(previews) == 1
    assert previews[0].conflicted is True
    assert previews[0].target_path.name == "Fate_Saber_001.jpg"


def test_apply_rename_and_rollback(rename_env: None, tmp_path: Path) -> None:
    source = tmp_path / "fate-original.png"
    source.write_bytes(b"z")
    _register_image_with_metadata(source, series="Fate", characters=["Saber"], exif_data={"Year": 2006})

    engine = RenameEngine()
    result = engine.apply_rename([source], rule=RenameRule(template="{series}_{character}_{year}"))

    assert result.applied is True
    assert result.dry_run is False
    assert len(result.previews) == 1

    target = result.previews[0].target_path
    assert target.exists()
    assert not source.exists()

    rollback = engine.rollback_last_batch()
    assert rollback is not None
    assert rollback.rolled_back is True
    assert source.exists()
    assert not target.exists()


def test_dry_run_does_not_touch_files(rename_env: None, tmp_path: Path) -> None:
    source = tmp_path / "dryrun.jpg"
    source.write_bytes(b"x")
    _register_image_with_metadata(source, series="One Piece", characters=["Luffy"])

    engine = RenameEngine()
    result = engine.apply_rename(
        [source],
        rule=RenameRule(template="{series}_{character}_{index}"),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.applied is False
    assert source.exists()


def test_windows_filename_rules_are_enforced(rename_env: None, tmp_path: Path) -> None:
    source = tmp_path / "win.jpg"
    source.write_bytes(b"x")
    _register_image_with_metadata(source, exif_data={"Artist": "CON"})

    engine = RenameEngine()
    previews = engine.preview_rename([source], rule=RenameRule(template="{artist_guess}"))

    assert len(previews) == 1
    assert previews[0].target_path.name == "CON_file.jpg"


def test_missing_metadata_uses_configurable_defaults(rename_env: None, tmp_path: Path) -> None:
    source = tmp_path / "missing.jpg"
    source.write_bytes(b"x")
    _register_image_with_metadata(source)

    engine = RenameEngine()
    rule = RenameRule(
        template="{series}_{year}_{source}",
        unknown_defaults={
            "series": "fallback_series",
            "character": "fallback_character",
            "variant": "fallback_variant",
            "artist_guess": "fallback_artist",
            "source": "fallback_source",
            "index": "999",
            "year": "1999",
        },
    )

    previews = engine.preview_rename([source], rule=rule)

    assert len(previews) == 1
    assert previews[0].target_path.stem.startswith("fallback_series_1999_fallback_source")


def test_preview_mode_reports_conflicts(rename_env: None, tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"1")
    second.write_bytes(b"2")

    _register_image_with_metadata(first, series="Bleach", characters=["Rukia"])
    _register_image_with_metadata(second, series="Bleach", characters=["Rukia"])

    engine = RenameEngine()
    previews = engine.preview_rename([first, second], rule=RenameRule(template="{series}_{character}"))

    assert len(previews) == 2
    assert any(preview.conflicted for preview in previews)
