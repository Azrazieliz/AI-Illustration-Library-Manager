from __future__ import annotations

from engine.database.models.character import Character
from engine.services.base_service import BaseService


class CharacterService(BaseService[Character]):
    """Service layer for character entities."""

    def create_character(self, *, name: str, series_id: int | None = None) -> Character:
        character = Character(name=name, series_id=series_id)
        self.add(character)
        self.commit()
        return character

    def get_character(self, identifier: int) -> Character | None:
        return self.get_by_id(Character, identifier)

    def rename_character(self, character: Character, new_name: str) -> Character:
        character.name = new_name
        self.commit()
        return character

    def merge_character(self, source: Character, target: Character) -> Character:
        for image in source.images:
            image.characters.append(target)
        self.session.delete(source)
        self.commit()
        return target

    def move_character(self, character: Character, series_id: int | None) -> Character:
        character.series_id = series_id
        self.commit()
        return character

    def list_characters(self) -> list[Character]:
        return list(self.session.query(Character).order_by(Character.name).all())
