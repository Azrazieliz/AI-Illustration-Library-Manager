from __future__ import annotations

from pathlib import Path

from engine.database.models.embedding import Embedding
from engine.database.models.image import Image
from engine.database.models.metadata import MetadataRecord
from engine.database.models.tag import Tag
from engine.repositories.base_repository import BaseRepository


class TaggingRepository(BaseRepository[Image]):
    """Repository providing persistence and provenance for automatic tagging."""

    _provenance_store: dict[tuple[int, str], list[str]] = {}

    def __init__(self) -> None:
        super().__init__(Image)

    def get_image_by_path(self, path: str | Path) -> Image | None:
        return self.session.query(Image).filter(Image.original_path == str(path)).first()

    def get_metadata_by_image_id(self, image_id: int) -> MetadataRecord | None:
        return self.session.query(MetadataRecord).filter(MetadataRecord.image_id == image_id).first()

    def get_embedding_by_image_id(self, image_id: int) -> Embedding | None:
        return self.session.query(Embedding).filter(Embedding.image_id == image_id).first()

    def list_all_embeddings(self) -> list[Embedding]:
        return list(self.session.query(Embedding).all())

    def get_or_create_tag(self, *, name: str, category: str | None = None) -> Tag:
        tag = self.session.query(Tag).filter(Tag.name == name).first()
        if tag is not None:
            return tag
        tag = Tag(name=name, category=category)
        self.add(tag)
        self.flush()
        return tag

    def assign_tag(self, image: Image, tag: Tag) -> None:
        if tag not in image.tags:
            image.tags.append(tag)

    def commit_changes(self) -> None:
        self.commit()

    def save_provenance(self, *, image_id: int, tag_name: str, provenance: list[str]) -> None:
        self._provenance_store[(image_id, tag_name)] = list(provenance)

    def get_provenance(self, *, image_id: int, tag_name: str) -> list[str]:
        return list(self._provenance_store.get((image_id, tag_name), []))
