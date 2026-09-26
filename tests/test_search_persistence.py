from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.image_repository import ImageRepository
from engine.search import SearchEngine


@pytest.fixture()
def search_persistence_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace", tmp_path)
    monkeypatch.setattr(settings, "database_directory", Path("database"))
    monkeypatch.setattr(settings, "embedding_directory", tmp_path / "cache" / "embeddings")
    database_manager._engine = None
    database_manager._session_factory = None
    database_manager._initialized = False
    database_manager.__init__()


def _store_embedding(path: Path, vector: list[float]) -> int:
    image = ImageRepository().create_image(
        original_path=str(path),
        filename=path.name,
        extension=path.suffix,
    )
    artifact = path.with_suffix(".npy")
    np.save(artifact, np.asarray(vector, dtype=np.float32), allow_pickle=False)
    EmbeddingRepository().create_embedding_record(
        image_id=image.id,
        vector_path=str(artifact),
        model_name="test-provider",
        model_version="1",
    )
    return image.id


def test_search_reloads_persisted_embeddings_after_engine_recreation(search_persistence_env: None, tmp_path: Path) -> None:
    first = _store_embedding(tmp_path / "first.png", [1.0, 0.0, 0.0])
    _store_embedding(tmp_path / "second.png", [0.0, 1.0, 0.0])

    result = SearchEngine().search(query_vector=[1.0, 0.0, 0.0], top_k=2)

    assert result.matches[0].image_id == first
    assert result.matches[0].similarity == pytest.approx(1.0, rel=1e-6)