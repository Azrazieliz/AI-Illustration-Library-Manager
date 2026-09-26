from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from engine.database.models.duplicate import DuplicateRecord
from engine.database.models.dataset import DatasetRecord
from engine.database.models.embedding import Embedding
from engine.database.models.hash import HashModel
from engine.database.models.image import Image
from engine.database.models.metadata import MetadataRecord
from engine.database.models.tag import Tag
from engine.database.session import session_scope
from engine.repositories.base_repository import BaseRepository

if TYPE_CHECKING:
    from engine.dataset.dataset_models import DatasetEntry


class DatasetRepository(BaseRepository[Image]):
    """Repository providing source data for dataset entry construction."""

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

    def get_dataset_entry(self, image_id: int) -> DatasetEntry | None:
        from engine.dataset.dataset_models import DatasetEntry

        with session_scope() as session:
            image = session.get(Image, image_id)
            if image is None:
                return None
            record = session.query(DatasetRecord).filter(DatasetRecord.image_uuid == image.uuid).one_or_none()
            if record is None:
                return None
            return DatasetEntry(
                image_id=image.id,
                path=Path(image.original_path),
                payload={},
                confidence_score=record.confidence_score,
                quality_score=record.quality_score,
                completeness_score=record.completeness_score,
                provenance=list(record.provenance),
                built_at=record.created_at,
                updated_at=record.updated_at,
                dataset_uuid=record.uuid,
                image_uuid=record.image_uuid,
                caption=record.caption,
                tag_ids=list(record.tag_ids),
                negative_tags=list(record.negative_tags),
                character_ids=list(record.character_ids),
                series_ids=list(record.series_ids),
                artist_ids=list(record.artist_ids),
                embedding_uuid=record.embedding_uuid,
                content_hash=record.hash,
                dataset_split=record.dataset_split,
                format=record.format,
            )

    def list_dataset_records(self) -> list[DatasetRecord]:
        return list(self.session.query(DatasetRecord).order_by(DatasetRecord.id).all())

    def delete_dataset_record(self, dataset_uuid: str) -> bool:
        with session_scope() as session:
            record = session.query(DatasetRecord).filter(DatasetRecord.uuid == dataset_uuid).one_or_none()
            if record is None:
                return False
            session.delete(record)
            return True

    def upsert_dataset_entry(self, entry: DatasetEntry) -> bool:
        if not entry.image_uuid:
            raise ValueError("Dataset entry requires an image UUID")
        with session_scope() as session:
            record = session.query(DatasetRecord).filter(DatasetRecord.image_uuid == entry.image_uuid).one_or_none()
            created = record is None
            if record is None:
                record = DatasetRecord(uuid=entry.dataset_uuid)
                session.add(record)
            else:
                entry.dataset_uuid = record.uuid
                entry.built_at = record.created_at

            record.image_uuid = entry.image_uuid
            record.caption = entry.caption
            record.tag_ids = list(entry.tag_ids)
            record.negative_tags = list(entry.negative_tags)
            record.character_ids = list(entry.character_ids)
            record.series_ids = list(entry.series_ids)
            record.artist_ids = list(entry.artist_ids)
            record.embedding_uuid = entry.embedding_uuid
            record.hash = entry.content_hash
            record.dataset_split = entry.dataset_split
            record.format = entry.format
            record.confidence_score = entry.confidence_score
            record.quality_score = entry.quality_score
            record.completeness_score = entry.completeness_score
            record.provenance = list(entry.provenance)
            return created

    def save_dataset_provenance(self, image_id: int, provenance: list[str]) -> None:
        if any(not isinstance(source, str) for source in provenance):
            raise ValueError("Dataset provenance must contain only strings")
        with session_scope() as session:
            image = session.get(Image, image_id)
            if image is None:
                raise ValueError(f"Image not found: {image_id}")
            record = session.query(DatasetRecord).filter(DatasetRecord.image_uuid == image.uuid).one_or_none()
            if record is None:
                raise ValueError(f"Dataset entry not found for image: {image_id}")
            record.provenance = list(provenance)

    def get_dataset_provenance(self, image_id: int) -> list[str]:
        entry = self.get_dataset_entry(image_id)
        return [] if entry is None else list(entry.provenance)
