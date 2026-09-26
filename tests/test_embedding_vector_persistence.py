from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.embeddings import EmbeddingEngine, MockProvider
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.image_repository import ImageRepository


@pytest.fixture()
def embedding_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace", tmp_path)
    monkeypatch.setattr(settings, "database_directory", Path("database"))
    monkeypatch.setattr(settings, "embedding_directory", tmp_path / "cache" / "embeddings")
    monkeypatch.setattr(settings, "cache_directory", tmp_path / "cache")
    monkeypatch.setattr(settings, "log_directory", tmp_path / "logs")

    database_manager._engine = None
    database_manager._session_factory = None
    database_manager._initialized = False
    database_manager.__init__()


def test_embedding_worker_persists_provider_vector(embedding_env: None, tmp_path: Path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image")
    image = ImageRepository().create_image(
        original_path=str(image_path),
        filename=image_path.name,
        extension=image_path.suffix,
    )
    provider = MockProvider(dimensions=16)
    provider.initialize()
    expected = provider.extract(image_path)

    result = EmbeddingEngine(provider=provider).process_path(image_path)

    assert result is not None
    record = EmbeddingRepository().get_by_image_id(image.id)
    assert record is not None
    artifact = Path(record.vector_path)
    assert artifact.is_file()
    assert np.load(artifact, allow_pickle=False).tolist() == pytest.approx(expected)