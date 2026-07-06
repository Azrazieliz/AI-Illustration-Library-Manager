from __future__ import annotations

from engine.database.models.image import Image
from engine.database.models.tag import Tag
from engine.services.base_service import BaseService


class TagService(BaseService[Tag]):
    """Service layer for tag entities and associations."""

    def create_tag(self, *, name: str, category: str | None = None) -> Tag:
        tag = Tag(name=name, category=category)
        self.add(tag)
        self.commit()
        return tag

    def delete_tag(self, tag: Tag) -> None:
        self.session.delete(tag)
        self.commit()

    def assign_tag(self, image: Image, tag: Tag) -> Image:
        if tag not in image.tags:
            image.tags.append(tag)
        self.commit()
        return image

    def remove_tag(self, image: Image, tag: Tag) -> Image:
        if tag in image.tags:
            image.tags.remove(tag)
        self.commit()
        return image

    def list_tags(self) -> list[Tag]:
        return list(self.session.query(Tag).order_by(Tag.name).all())
