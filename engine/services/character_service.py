from __future__ import annotations

from engine.database.models.character import Character
from engine.repositories.character_repository import CharacterRepository
from engine.services.base_service import BaseService


class CharacterService(BaseService[Character]):
    """Service layer for character entities."""

    def __init__(self, repository: CharacterRepository | None = None) -> None:
        super().__init__(repository or CharacterRepository())
        self.repository = repository or CharacterRepository()

    def create_character(self, *, name: str, series_id: int | None = None) -> Character:
        return self.repository.create_character(name=name, series_id=series_id)

    def get_character(self, identifier: int) -> Character | None:
        return self.repository.get_character(identifier)

    def rename_character(self, character: Character, new_name: str) -> Character:
        return self.repository.rename_character(character, new_name)

    def merge_character(self, source: Character, target: Character) -> Character:
        return self.repository.merge_character(source, target)

    def move_character(self, character: Character, series_id: int | None) -> Character:
        return self.repository.move_character(character, series_id)

    def list_characters(self) -> list[Character]:
        return self.repository.list_characters()
