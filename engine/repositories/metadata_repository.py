from __future__ import annotations

from typing import Any

from engine.database.models.metadata import MetadataRecord
from engine.repositories.base_repository import BaseRepository


class MetadataRepository(BaseRepository[MetadataRecord]):
    """Repository for :class:`~engine.database.models.metadata.MetadataRecord` records."""

    def __init__(self) -> None:
        super().__init__(MetadataRecord)

    def get_by_image_id(self, image_id: int) -> MetadataRecord | None:
        """Retrieve metadata for a specific image."""
        return self.session.query(MetadataRecord).filter(
            MetadataRecord.image_id == image_id
        ).first()

    def create_metadata_record(
        self,
        *,
        image_id: int,
        aspect_ratio: float | None = None,
        orientation: str | None = None,
        mime_type: str | None = None,
        color_mode: str | None = None,
        bit_depth: int | None = None,
        dpi: str | None = None,
        has_icc_profile: bool = False,
        is_animated: bool = False,
        frame_count: int | None = None,
        exif_data: str | None = None,
    ) -> MetadataRecord:
        """Create and persist a new metadata record."""
        record = MetadataRecord(
            image_id=image_id,
            aspect_ratio=aspect_ratio,
            orientation=orientation,
            mime_type=mime_type,
            color_mode=color_mode,
            bit_depth=bit_depth,
            dpi=dpi,
            has_icc_profile=has_icc_profile,
            is_animated=is_animated,
            frame_count=frame_count,
            exif_data=exif_data,
        )
        self.add(record)
        self.commit()
        return record

    def update_metadata_record(
        self, record: MetadataRecord, **changes: Any
    ) -> MetadataRecord:
        """Update an existing metadata record."""
        for key, value in changes.items():
            setattr(record, key, value)
        self.commit()
        return record

    def delete_metadata_record(self, record: MetadataRecord) -> None:
        """Delete a metadata record."""
        self.delete(record)
        self.commit()

    def list_all_metadata(self) -> list[MetadataRecord]:
        """List all metadata records."""
        return list(self.session.query(MetadataRecord).all())
