from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from engine.database.models.duplicate import DuplicateRecord
from engine.database.models.embedding import Embedding
from engine.database.models.image import Image
from engine.repositories.base_repository import BaseRepository


@dataclass(slots=True)
class KnowledgeGraphImageContext:
    image: Image
    embedding: Embedding | None
    duplicates: list[DuplicateRecord] = field(default_factory=list)
    artists: list[str] = field(default_factory=list)


class KnowledgeGraphRepository(BaseRepository[Image]):
    """Repository supplying entities needed for graph construction."""

    def __init__(self) -> None:
        super().__init__(Image)

    def get_image_by_path(self, path: str | Path) -> Image | None:
        return self.session.query(Image).filter(Image.original_path == str(path)).first()

    def get_embedding_by_image_id(self, image_id: int) -> Embedding | None:
        return self.session.query(Embedding).filter(Embedding.image_id == image_id).first()

    def get_duplicate_records_for_image(self, image_id: int) -> list[DuplicateRecord]:
        return list(
            self.session.query(DuplicateRecord)
            .filter(
                (DuplicateRecord.image_a_id == image_id)
                | (DuplicateRecord.image_b_id == image_id)
            )
            .all()
        )

    def build_image_context(self, path: str | Path, metadata: dict | None = None) -> KnowledgeGraphImageContext | None:
        image = self.get_image_by_path(path)
        if image is None:
            return None

        artists: list[str] = []
        payload = metadata or {}
        artist = payload.get("artist")
        if isinstance(artist, str) and artist.strip():
            artists.append(artist.strip())

        artists_payload = payload.get("artists")
        if isinstance(artists_payload, list):
            for item in artists_payload:
                if isinstance(item, str) and item.strip():
                    artists.append(item.strip())

        # Infer artist-like tags by category when available.
        for tag in image.tags:
            if tag.category and tag.category.lower() == "artist":
                artists.append(tag.name)

        deduped_artists: list[str] = []
        seen: set[str] = set()
        for name in artists:
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                deduped_artists.append(name)

        return KnowledgeGraphImageContext(
            image=image,
            embedding=self.get_embedding_by_image_id(image.id),
            duplicates=self.get_duplicate_records_for_image(image.id),
            artists=deduped_artists,
        )
