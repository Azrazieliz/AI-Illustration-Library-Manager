from __future__ import annotations

from typing import Any

from engine.database.models.embedding import Embedding
from engine.repositories.base_repository import BaseRepository


class EmbeddingRepository(BaseRepository[Embedding]):
    """Repository for :class:`~engine.database.models.embedding.Embedding` records."""

    def __init__(self) -> None:
        super().__init__(Embedding)

    def get_by_image_id(self, image_id: int) -> Embedding | None:
        """Retrieve embedding for a specific image."""
        return self.session.query(Embedding).filter(
            Embedding.image_id == image_id
        ).first()

    def create_embedding_record(
        self,
        *,
        image_id: int,
        vector_path: str,
        model_name: str,
        model_version: str,
    ) -> Embedding:
        """Create and persist a new embedding record."""
        record = Embedding(
            image_id=image_id,
            vector_path=vector_path,
            model_name=model_name,
            model_version=model_version,
        )
        self.add(record)
        return record

    def update_embedding_record(
        self,
        record: Embedding,
        **kwargs: Any,
    ) -> Embedding:
        """Update an existing embedding record."""
        for key, value in kwargs.items():
            if hasattr(record, key):
                setattr(record, key, value)
        self.add(record)
        return record

    def delete_embedding_record(self, record: Embedding) -> None:
        """Delete an embedding record."""
        self.delete(record)

    def list_all_embeddings(self) -> list[Embedding]:
        """List all embedding records."""
        return self.session.query(Embedding).all()
