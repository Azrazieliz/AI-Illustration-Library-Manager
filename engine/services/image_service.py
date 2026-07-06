from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.database.models.image import Image
from engine.repositories.image_repository import ImageRepository
from engine.services.base_service import BaseService


class ImageService(BaseService[Image]):
    """Service layer for image entities."""

    def __init__(self, repository: ImageRepository | None = None) -> None:
        super().__init__(repository or ImageRepository())
        self.repository = repository or ImageRepository()

    def create_image(self, *, original_path: str | Path, filename: str, extension: str | None = None) -> Image:
        return self.repository.create_image(
            original_path=original_path,
            filename=filename,
            extension=extension,
        )

    def update_image(self, image: Image, **changes: Any) -> Image:
        return self.repository.update_image(image, **changes)

    def delete_image(self, image: Image) -> None:
        self.repository.delete_image(image)

    def get_image(self, identifier: int) -> Image | None:
        return self.repository.get_image(identifier)

    def get_by_path(self, path: str | Path) -> Image | None:
        return self.repository.get_by_path(path)

    def list_images(self) -> list[Image]:
        return self.repository.list_images()

    def mark_thumbnail_created(self, image: Image) -> Image:
        return self.repository.mark_thumbnail_created(image)

    def mark_embedding_created(self, image: Image) -> Image:
        return self.repository.mark_embedding_created(image)

    def update_scan_time(self, image: Image, timestamp: datetime | None = None) -> Image:
        return self.repository.update_scan_time(image, timestamp=timestamp)
