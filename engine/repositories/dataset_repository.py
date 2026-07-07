from __future__ import annotations

from pathlib import Path

from engine.database.models.duplicate import DuplicateRecord
from engine.database.models.embedding import Embedding
from engine.database.models.hash import HashModel
from engine.database.models.image import Image
from engine.database.models.metadata import MetadataRecord
from engine.database.models.tag import Tag
from engine.repositories.base_repository import BaseRepository


class DatasetRepository(BaseRepository[Image]):
    """Repository providing source data for dataset entry construction."""

    _dataset_provenance: dict[int, list[str]] = {}

    def __init__(self) -> None:
        super().__init__(Image)

    def get_image_by_path(self, path: str | Path) -> Image | None:
        return self.session.query(Image).filter(Image.original_path == str(path)).first()

    def get_metadata_by_image_id(self, image_id: int) -> MetadataRecord | None:
        return self.session.query(MetadataRecord).filter(MetadataRecord.image_id == image_id).first()

    def get_hash_by_image_id(self, image_id: int) -> HashModel | None:
        return self.session.query(HashModel).filter(HashModel.image_id == image_id).first()

    def get_embedding_by_image_id(self, image_id: int) -> Embedding | None:
        return self.session.query(Embedding).filter(Embedding.image_id == image_id).first()

    def get_duplicates_for_image(self, image_id: int) -> list[DuplicateRecord]:
        return list(
            self.session.query(DuplicateRecord)
            .filter(
                (DuplicateRecord.image_a_id == image_id)
                | (DuplicateRecord.image_b_id == image_id)
            )
            .all()
        )

    def get_tags_for_image(self, image_id: int) -> list[Tag]:
        image = self.session.query(Image).filter(Image.id == image_id).first()
        if image is None:
            return []
        return list(image.tags)

    def save_dataset_provenance(self, image_id: int, provenance: list[str]) -> None:
        self._dataset_provenance[image_id] = list(provenance)

    def get_dataset_provenance(self, image_id: int) -> list[str]:
        return list(self._dataset_provenance.get(image_id, []))
