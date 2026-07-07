from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from engine.database.models.image import Image
from engine.repositories.base_repository import BaseRepository
from engine.repositories.dataset_repository import DatasetRepository


class OrganizerRepository(BaseRepository[Image]):
    """Repository for organizer metadata resolution and moved-path persistence."""

    _dataset_repo = DatasetRepository()

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(Image, session=session)

    def get_image_by_path(self, path: str | Path) -> Image | None:
        value = str(path)
        return (
            self.session.query(Image)
            .filter(or_(Image.original_path == value, Image.current_path == value))
            .first()
        )

    def get_organization_metadata(self, path: str | Path) -> tuple[int, dict[str, str]] | None:
        image = self.get_image_by_path(path)
        if image is None:
            return None

        metadata_record = image.metadata_record
        exif = self._parse_exif(metadata_record.exif_data if metadata_record is not None else None)
        characters = sorted(character.name for character in image.characters)

        dataset_provenance = self._dataset_repo.get_dataset_provenance(image.id)
        source_value = self._pick_first(exif, ["source", "Source"]) or (dataset_provenance[0] if dataset_provenance else "")

        year_value = self._extract_year(exif)
        if not year_value:
            year_value = str(image.scan_date.year) if image.scan_date is not None else str(image.created_at.year)

        file_stem = Path(path).stem
        first_letter = file_stem[0].upper() if file_stem else ""

        return (
            image.id,
            {
                "series": image.series.name if image.series is not None else "",
                "character": characters[0] if characters else "",
                "source": source_value,
                "year": year_value,
                "first_letter": first_letter,
                "unknown": "unknown",
            },
        )

    def update_image_path(self, image_id: int, new_path: Path, *, commit: bool = True) -> None:
        image = self.get_by_id(image_id)
        if image is None:
            return
        image.current_path = str(new_path)
        image.filename = new_path.name
        image.extension = new_path.suffix
        if commit:
            self.commit()

    @staticmethod
    def _parse_exif(exif_data: str | None) -> dict[str, object]:
        if not exif_data:
            return {}
        try:
            payload = json.loads(exif_data)
            if isinstance(payload, dict):
                return payload
        except Exception:
            return {}
        return {}

    @staticmethod
    def _pick_first(payload: dict[str, object], keys: list[str]) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _extract_year(payload: dict[str, object]) -> str:
        for key in ["year", "Year", "DateTimeOriginal", "date", "Date"]:
            value = payload.get(key)
            if isinstance(value, int) and 1000 <= value <= 9999:
                return str(value)
            if isinstance(value, str):
                match = re.search(r"(19|20)\d{2}", value)
                if match:
                    return match.group(0)
        return ""
