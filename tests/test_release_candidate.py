from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import settings
from engine.config.bootstrap import bootstrap_directories
from engine.logging import configure, shutdown
from engine.release.dependencies import validate_runtime_dependencies
from engine.release.diagnostics import collect_runtime_diagnostics
from engine.release.documentation import generate_release_documents
from engine.release.metadata import load_release_metadata
from engine.release.performance import PerformanceTracker


def test_startup_configuration_bootstrap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_directory", tmp_path / "database")
    monkeypatch.setattr(settings, "cache_directory", tmp_path / "cache")
    monkeypatch.setattr(settings, "log_directory", tmp_path / "logs")
    monkeypatch.setattr(settings, "thumbnail_directory", tmp_path / "cache" / "thumbnails")
    monkeypatch.setattr(settings, "embedding_directory", tmp_path / "cache" / "embeddings")
    monkeypatch.setattr(settings, "knowledge_directory", tmp_path / "knowledge")
    monkeypatch.setattr(settings, "models_directory", tmp_path / "models")
    monkeypatch.setattr(settings, "datasets_directory", tmp_path / "datasets")

    bootstrap_directories()

    assert (tmp_path / "database").exists()
    assert (tmp_path / "cache").exists()
    assert (tmp_path / "logs").exists()


def test_logging_startup_and_shutdown() -> None:
    logger = configure(app_name="AILM", version="1.0.0")
    logger.info("release-test")
    shutdown()

    assert logger is not None


def test_release_metadata_and_version_information() -> None:
    metadata = load_release_metadata()
    assert metadata.app_name == settings.app_name
    assert metadata.version == settings.version
    assert metadata.release_channel in {"stable", "rc", "nightly"} or isinstance(metadata.release_channel, str)


def test_runtime_diagnostics_snapshot() -> None:
    diagnostics = collect_runtime_diagnostics()
    assert diagnostics.active_threads >= 1
    assert diagnostics.traced_memory_current_bytes >= 0
    assert diagnostics.traced_memory_peak_bytes >= diagnostics.traced_memory_current_bytes


def test_dependency_validation() -> None:
    result = validate_runtime_dependencies()
    assert "pydantic" in result.installed
    assert isinstance(result.missing, list)


def test_performance_statistics_tracker() -> None:
    tracker = PerformanceTracker()
    tracker.start("startup")
    snapshot = tracker.stop("startup")
    assert snapshot.label == "startup"
    assert snapshot.elapsed_seconds >= 0.0


def test_documentation_generation(tmp_path: Path) -> None:
    metadata = load_release_metadata()
    files = generate_release_documents(root=tmp_path, metadata=metadata)
    assert len(files) == 5
    for path in files:
        assert path.exists()


def test_resource_cleanup_idempotent_shutdown() -> None:
    configure(app_name="AILM", version="1.0.0")
    shutdown()
    shutdown()

    assert True
