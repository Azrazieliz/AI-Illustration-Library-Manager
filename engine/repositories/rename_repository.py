from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from engine.database.models.image import Image
from engine.rename.rename_models import RenameContext
from engine.repositories.base_repository import BaseRepository
from engine.repositories.dataset_repository import DatasetRepository


class RenameRepository(BaseRepository[Image]):
    """Repository for collecting rename context and persisting renamed paths."""

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(Image, session=session)
        self._dataset_repository = DatasetRepository()

    def get_image_by_path(self, path: str | Path) -> Image | None:
        text_path = str(path)
        return (
            self.session.query(Image)
            .filter(or_(Image.original_path == text_path, Image.current_path == text_path))
            .first()
        )

    def build_context(self, path: str | Path) -> RenameContext | None:
        image = self.get_image_by_path(path)
        if image is None:
            return None

        source_path = Path(path)
        characters = sorted(character.name for character in image.characters)
        primary_character = characters[0] if characters else None

        exif = self._parse_exif(image)
        artist_guess = self._pick_first(exif, ["artist", "Artist", "creator", "Creator"])
        metadata = image.metadata_record
        source_value = self._pick_first(exif, ["source", "Source"])
        provenance = self._dataset_repository.get_dataset_provenance(image.id)
        if not source_value and metadata is not None and provenance:
            source_value = provenance[0]

        variant = self._extract_variant(source_path.stem)
        year = self._extract_year(exif) or ""

        extension = source_path.suffix or (image.extension or "")
        return RenameContext(
            image_id=image.id,
            source_path=source_path,
            extension=extension,
            values={
                "series": image.series.name if image.series is not None else "",
                "character": primary_character or "",
                "variant": variant,
                "artist_guess": artist_guess or "",
                "source": source_value or "",
                "year": year,
            },
        )

    def update_image_path(self, *, image_id: int, new_path: Path, commit: bool = True) -> None:
        image = self.get_by_id(image_id)
        if image is None:
            return

        image.current_path = str(new_path)
        image.filename = new_path.name
        image.extension = new_path.suffix
        if commit:
            self.commit()

    @staticmethod
    def _parse_exif(image: Image) -> dict[str, object]:
        metadata = image.metadata_record
        if metadata is None or not metadata.exif_data:
            return {}
        try:
            payload = json.loads(metadata.exif_data)
            if isinstance(payload, dict):
                return payload
        except Exception:
            return {}
        return {}

    @staticmethod
    def _pick_first(exif: dict[str, object], keys: list[str]) -> str | None:
        for key in keys:
            value = exif.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_variant(stem: str) -> str:
        if "__" in stem:
            return "base"
        parts = re.split(r"[_\-]+", stem)
        if not parts:
            return ""
        candidate = parts[-1].strip()
        if not candidate:
            return ""
        if candidate.isdigit():
            return ""
        return candidate.lower()

    @staticmethod
    def _extract_year(exif: dict[str, object]) -> str | None:
        candidates = [
            exif.get("year"),
            exif.get("Year"),
            exif.get("DateTimeOriginal"),
            exif.get("date"),
            exif.get("Date"),
        ]
        for value in candidates:
            if isinstance(value, int):
                if 1000 <= value <= 9999:
                    return str(value)
            if isinstance(value, str):
                match = re.search(r"(19|20)\d{2}", value)
                if match:
                    return match.group(0)
        return None
