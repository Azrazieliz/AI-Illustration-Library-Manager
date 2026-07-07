from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from engine.character_database.character_database_models import CharacterRecord, SeriesRecord
from engine.database.models.character import Character
from engine.database.models.image import Image
from engine.database.models.series import Series
from engine.recognition.recognition_models import RecognitionAssignment, RecognitionContext, RecognitionOutput
from engine.repositories.base_repository import BaseRepository
from engine.repositories.review_repository import ReviewRepository


class RecognitionRepository(BaseRepository[Image]):
    """Repository that persists recognition assignments for images."""

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(Image, session=session)
        self.review_repository = ReviewRepository(session=session)

    def get_image_by_path(self, path: str) -> Image | None:
        """Return image record by original path."""
        return self.session.query(Image).filter(Image.original_path == path).first()

    def build_context(self, *, image: Image, output: RecognitionOutput, path: Path) -> RecognitionContext:
        folder_parts = [part for part in path.parent.parts if part]
        return RecognitionContext(
            image_id=image.id,
            path=path,
            filename=path.name,
            folder_name=path.parent.name if path.parent.name else "",
            folder_parts=folder_parts,
            current_series_id=image.series_id,
            current_series_name=image.series.name if image.series is not None else None,
            current_character_names=[character.name for character in image.characters],
            metadata=self._metadata_context(image),
            review_history=self._review_history(image.id),
            ai_series_name=output.series.name if output.series is not None else None,
            ai_character_names=[label.name for label in output.characters],
        )

    def metadata_series_names(self, *, image: Image) -> list[str]:
        names: list[str] = []
        if image.series is not None:
            names.append(image.series.name)
        metadata = image.metadata_record
        if metadata is not None and metadata.exif_data:
            names.extend(self._extract_names(metadata.exif_data))
        return self._dedupe(names)

    def review_series_names(self, *, image: Image) -> list[str]:
        names: list[str] = []
        for item in self.review_repository.list_review_items():
            if item.image_id != image.id:
                continue
            if item.series:
                names.append(item.series)
            if isinstance(item.proposed_value, dict) and item.proposed_value.get("series_name"):
                names.append(str(item.proposed_value["series_name"]))
        return self._dedupe(names)

    def filename_hints(self, *, context: RecognitionContext) -> list[str]:
        stem = context.filename.rsplit(".", maxsplit=1)[0]
        pieces = [piece for piece in stem.replace("_", " ").replace("-", " ").split() if piece]
        pieces.append(stem)
        return self._dedupe(pieces)

    def folder_hints(self, *, context: RecognitionContext) -> list[str]:
        return self._dedupe([part for part in context.folder_parts if part] + ([context.folder_name] if context.folder_name else []))

    def create_review_item(
        self,
        *,
        image: Image,
        assignment: dict[str, Any],
        output: RecognitionOutput,
        reason: str,
        review_series_name: str | None,
        review_character_name: str | None,
    ):
        return self.review_repository.create_review_item(
            image_id=image.id,
            source_path=Path(image.current_path or image.original_path),
            operation_type="recognition",
            confidence=float(assignment.get("confidence", output.overall_confidence or 0.0)),
            proposed_value={
                "character_id": assignment.get("character_id"),
                "series_id": assignment.get("series_id"),
                "character_name": assignment.get("character_name"),
                "series_name": assignment.get("series_name") or review_series_name,
                "matched_alias": assignment.get("matched_alias"),
                "source_labels": assignment.get("source_labels", []),
                "score_breakdown": assignment.get("score_breakdown", {}),
                "reason": reason,
            },
            current_value={
                "image_id": image.id,
                "series_name": image.series.name if image.series is not None else None,
                "characters": [character.name for character in image.characters],
                "provider_series": output.series.name if output.series is not None else None,
                "provider_characters": [label.name for label in output.characters],
            },
            series=review_series_name,
            character=review_character_name,
        )

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

    def apply_assignment(self, *, image: Image, assignment: RecognitionAssignment, commit: bool = True) -> tuple[Series | None, list[Character]]:
        series_name = assignment.series_name
        character_names = [assignment.character_name] if assignment.character_name else []
        return self.apply_recognition(image=image, series_name=series_name, character_names=character_names, commit=commit)

    def _metadata_context(self, image: Image) -> dict[str, Any]:
        metadata = image.metadata_record
        if metadata is None:
            return {}
        return {
            "mime_type": metadata.mime_type,
            "aspect_ratio": metadata.aspect_ratio,
            "orientation": metadata.orientation,
            "color_mode": metadata.color_mode,
            "exif_data": metadata.exif_data,
        }

    def _review_history(self, image_id: int) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for item in self.review_repository.list_review_items():
            if item.image_id != image_id:
                continue
            history.append(
                {
                    "review_id": item.review_id,
                    "status": item.status.value,
                    "confidence": item.confidence,
                    "series": item.series,
                    "character": item.character,
                    "proposed_value": item.proposed_value,
                    "current_value": item.current_value,
                }
            )
        return history

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

    @staticmethod
    def _extract_names(text: str) -> list[str]:
        tokens = [token.strip() for token in text.replace("{", " ").replace("}", " ").replace("[", " ").replace("]", " ").split()]
        return [token for token in tokens if token]

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = value.strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result
