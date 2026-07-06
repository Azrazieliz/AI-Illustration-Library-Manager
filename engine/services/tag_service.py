from __future__ import annotations

from engine.database.models.image import Image
from engine.database.models.tag import Tag
from engine.repositories.tag_repository import TagRepository
from engine.services.base_service import BaseService


class TagService(BaseService[Tag]):
    """Service layer for tag entities and associations."""

    def __init__(self, repository: TagRepository | None = None) -> None:
        super().__init__(repository or TagRepository())
        self.repository = repository or TagRepository()

    def create_tag(self, *, name: str, category: str | None = None) -> Tag:
        return self.repository.create_tag(name=name, category=category)

    def delete_tag(self, tag: Tag) -> None:
        self.repository.delete_tag(tag)

    def assign_tag(self, image: Image, tag: Tag) -> Image:
        return self.repository.assign_tag(image, tag)

    def remove_tag(self, image: Image, tag: Tag) -> Image:
        return self.repository.remove_tag(image, tag)

    def list_tags(self) -> list[Tag]:
        return self.repository.list_tags()
