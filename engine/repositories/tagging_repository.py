from __future__ import annotations

from math import isfinite
from pathlib import Path

from engine.database.models.embedding import Embedding
from engine.database.models.image import Image
from engine.database.models.metadata import MetadataRecord
from engine.database.models.tag import Tag
from engine.database.models.tag_provenance import TagProvenance
from engine.repositories.base_repository import BaseRepository


class TaggingRepository(BaseRepository[Image]):
    """Repository providing persistence and provenance for automatic tagging."""

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

    def save_provenance(
        self,
        *,
        image_id: int,
        tag_name: str,
        provenance: list[str],
        confidence: float,
        source_model: str | None = None,
        source_version: str | None = None,
        approved: bool = False,
        review_uuid: str | None = None,
    ) -> list[TagProvenance]:
        image = self.get_by_id(image_id)
        tag = self.session.query(Tag).filter(Tag.name == tag_name).one_or_none()
        if image is None or tag is None:
            raise ValueError("Cannot persist provenance for a missing image or tag")
        if not isfinite(confidence):
            raise ValueError("Tag provenance confidence must be finite")
        if not provenance or any(not isinstance(source, str) or not source.strip() for source in provenance):
            raise ValueError("Every generated tag requires at least one non-empty provenance source")
        if source_model is not None and (not isinstance(source_model, str) or not source_model.strip()):
            raise ValueError("source_model must be a non-empty string when provided")
        if source_version is not None and (not isinstance(source_version, str) or not source_version.strip()):
            raise ValueError("source_version must be a non-empty string when provided")

        records = [
            TagProvenance(
                image_uuid=image.uuid,
                tag_id=tag.id,
                source=source,
                source_model=source_model,
                source_version=source_version,
                confidence=confidence,
                approved=approved,
                review_uuid=review_uuid,
            )
            for source in provenance
        ]
        self.session.add_all(records)
        return records

    def get_provenance(self, *, image_id: int, tag_name: str) -> list[str]:
        return [record.source for record in self.list_provenance_records(image_id=image_id, tag_name=tag_name)]

    def list_provenance_records(self, *, image_id: int, tag_name: str) -> list[TagProvenance]:
        image = self.get_by_id(image_id)
        tag = self.session.query(Tag).filter(Tag.name == tag_name).one_or_none()
        if image is None or tag is None:
            return []
        return list(
            self.session.query(TagProvenance)
            .filter(TagProvenance.image_uuid == image.uuid, TagProvenance.tag_id == tag.id)
            .order_by(TagProvenance.id)
            .all()
        )
