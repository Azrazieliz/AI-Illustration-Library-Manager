from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.database.models.image import Image
from engine.services.base_service import BaseService


class ImageService(BaseService[Image]):
    """Service layer for image entities."""

    def create_image(self, *, original_path: str | Path, filename: str, extension: str | None = None) -> Image:
        image = Image(
            original_path=str(original_path),
            filename=filename,
            extension=extension,
            scan_date=datetime.now(timezone.utc),
        )
        self.add(image)
        self.commit()
        return image

    def update_image(self, image: Image, **changes: Any) -> Image:
        for key, value in changes.items():
            setattr(image, key, value)
        self.commit()
        return image

    def delete_image(self, image: Image) -> None:
        self.session.delete(image)
        self.commit()

    def get_image(self, identifier: int) -> Image | None:
        return self.get_by_id(Image, identifier)

    def get_by_path(self, path: str | Path) -> Image | None:
        return self.session.query(Image).filter(Image.original_path == str(path)).first()

    def list_images(self) -> list[Image]:
        return list(self.session.query(Image).order_by(Image.created_at).all())

    def mark_thumbnail_created(self, image: Image) -> Image:
        image.thumbnail_exists = True
        self.commit()
        return image

    def mark_embedding_created(self, image: Image) -> Image:
        image.embedding_exists = True
        self.commit()
        return image

    def update_scan_time(self, image: Image, timestamp: datetime | None = None) -> Image:
        image.scan_date = timestamp or datetime.now(timezone.utc)
        self.commit()
        return image
