from __future__ import annotations

from typing import Any

from engine.database.models.thumbnail import ThumbnailRecord
from engine.repositories.base_repository import BaseRepository


class ThumbnailRepository(BaseRepository[ThumbnailRecord]):
    """Repository for :class:`~engine.database.models.thumbnail.ThumbnailRecord`."""

    def __init__(self) -> None:
        super().__init__(ThumbnailRecord)

    def get_by_image_and_size(self, image_id: int, size: int) -> ThumbnailRecord | None:
        return (
            self.session.query(ThumbnailRecord)
            .filter(
                ThumbnailRecord.image_id == image_id,
                ThumbnailRecord.size == size,
            )
            .first()
        )

    def list_by_image(self, image_id: int) -> list[ThumbnailRecord]:
        return list(
            self.session.query(ThumbnailRecord)
            .filter(ThumbnailRecord.image_id == image_id)
            .all()
        )

    def create_thumbnail_record(
        self,
        *,
        image_id: int,
        size: int,
        format: str,
        file_path: str,
        file_size_bytes: int,
        cache_key: str,
        thumb_width: int,
        thumb_height: int,
    ) -> ThumbnailRecord:
        record = ThumbnailRecord(
            image_id=image_id,
            size=size,
            format=format,
            file_path=file_path,
            file_size_bytes=file_size_bytes,
            cache_key=cache_key,
            thumb_width=thumb_width,
            thumb_height=thumb_height,
        )
        self.add(record)
        self.commit()
        return record

    def update_thumbnail_record(
        self, record: ThumbnailRecord, **changes: Any
    ) -> ThumbnailRecord:
        for key, value in changes.items():
            setattr(record, key, value)
        self.commit()
        return record

    def delete_thumbnail_record(self, record: ThumbnailRecord) -> None:
        self.delete(record)
        self.commit()

    def list_all(self) -> list[ThumbnailRecord]:
        return list(self.session.query(ThumbnailRecord).all())
