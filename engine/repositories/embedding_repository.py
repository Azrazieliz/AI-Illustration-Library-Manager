from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from engine.database.models.embedding import Embedding
from engine.database.models.image import Image
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
        image = self.session.get(Image, image_id)
        if image is None:
            raise ValueError("Cannot create an embedding record for a missing image")
        dimension, dtype, checksum = self._read_artifact_metadata(vector_path)
        record = Embedding(
            image_id=image_id,
            image_uuid=image.uuid,
            vector_path=vector_path,
            model_name=model_name,
            model_version=model_version,
            dimension=dimension,
            dtype=dtype,
            storage_path=vector_path,
            checksum=checksum,
        )
        self.add(record)
        return record

    def update_embedding_record(
        self,
        record: Embedding,
        **kwargs: Any,
    ) -> Embedding:
        """Update an existing embedding record."""
        if "vector_path" in kwargs:
            vector_path = kwargs["vector_path"]
            dimension, dtype, checksum = self._read_artifact_metadata(vector_path)
            record.vector_path = vector_path
            record.storage_path = vector_path
            record.dimension = dimension
            record.dtype = dtype
            record.checksum = checksum
        for key in ("model_name", "model_version"):
            if key in kwargs:
                setattr(record, key, kwargs[key])
        if record.image_uuid is None and record.image is not None:
            record.image_uuid = record.image.uuid
        self.add(record)
        return record

    def delete_embedding_record(self, record: Embedding) -> None:
        """Delete an embedding record."""
        self.delete(record)

    def list_all_embeddings(self) -> list[Embedding]:
        """List all embedding records."""
        return self.session.query(Embedding).all()

    @staticmethod
    def _read_artifact_metadata(vector_path: str) -> tuple[int | None, str | None, str | None]:
        path = Path(vector_path)
        if not path.is_file():
            return None, None, None
        try:
            vector = np.load(path, allow_pickle=False)
        except (OSError, ValueError) as error:
            raise ValueError(f"Embedding artifact is not a readable NumPy array: {path}") from error
        if vector.ndim != 1 or vector.size == 0:
            raise ValueError(f"Embedding artifact must contain a non-empty vector: {path}")
        if not np.issubdtype(vector.dtype, np.number) or not np.isfinite(vector).all():
            raise ValueError(f"Embedding artifact contains unsupported or non-finite values: {path}")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        return int(vector.size), str(vector.dtype), checksum
