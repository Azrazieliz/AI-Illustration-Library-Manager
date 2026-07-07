from __future__ import annotations

from pathlib import Path

from engine.database.models.embedding import Embedding
from engine.database.models.image import Image
from engine.repositories.base_repository import BaseRepository


class SearchRepository(BaseRepository[Embedding]):
    """Repository for semantic search indexing/query source data."""

    def __init__(self) -> None:
        super().__init__(Embedding)

    def get_embedding_by_image_id(self, image_id: int) -> Embedding | None:
        """Return embedding row for one image id."""
        return self.session.query(Embedding).filter(Embedding.image_id == image_id).first()

    def get_embedding_by_path(self, path: str | Path) -> Embedding | None:
        """Return embedding row by image original path."""
        image = self.get_image_by_path(path)
        if image is None:
            return None
        return self.get_embedding_by_image_id(image.id)

    def get_image_by_path(self, path: str | Path) -> Image | None:
        """Return image row by original path."""
        return self.session.query(Image).filter(Image.original_path == str(path)).first()

    def get_image_by_id(self, image_id: int) -> Image | None:
        """Return image row by id."""
        return self.session.query(Image).filter(Image.id == image_id).first()

    def list_embeddings(self) -> list[Embedding]:
        """Return all embedding rows for batch indexing."""
        return list(self.session.query(Embedding).all())
