from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.orm import Session

from engine.database.models.character import Character
from engine.database.models.image import Image
from engine.database.models.series import Series
from engine.repositories.base_repository import BaseRepository


class RecognitionRepository(BaseRepository[Image]):
    """Repository that persists recognition assignments for images."""

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(Image, session=session)

    def get_image_by_path(self, path: str) -> Image | None:
        """Return image record by original path."""
        return self.session.query(Image).filter(Image.original_path == path).first()

    def apply_recognition(
        self,
        *,
        image: Image,
        series_name: str | None,
        character_names: list[str],
        commit: bool = True,
    ) -> tuple[Series | None, list[Character]]:
        """Apply recognized series and characters to an image record."""
        series = self._get_or_create_series(series_name) if series_name else None

        if series is not None:
            image.series_id = series.id

        characters: list[Character] = []
        if character_names:
            target_series_id = series.id if series is not None else image.series_id
            characters = [
                self._get_or_create_character(name=name, series_id=target_series_id)
                for name in character_names
            ]
            image.characters = characters

        if commit:
            self.commit()
        return series, characters

    def _get_or_create_series(self, name: str) -> Series:
        existing = self.session.query(Series).filter(Series.name == name).first()
        if existing is not None:
            return existing

        series = Series(name=name)
        self.add(series)
        self.flush()
        return series

    def _get_or_create_character(self, *, name: str, series_id: int | None) -> Character:
        existing = self.session.query(Character).filter(
            and_(Character.name == name, Character.series_id == series_id)
        ).first()
        if existing is not None:
            return existing

        character = Character(name=name, series_id=series_id)
        self.add(character)
        self.flush()
        return character
