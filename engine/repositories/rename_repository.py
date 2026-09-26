from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from engine.database.models.image import Image
from engine.database.models.rename_batch_state import RenameBatchStateRecord
from engine.rename.rename_models import RenameBatch, RenameBatchEntry, RenameContext
from engine.repositories.base_repository import BaseRepository


class RenameRepository(BaseRepository[Image]):
    """Repository for collecting rename context and persisting renamed paths."""

    _last_batch_state_key = "last_applied"

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(Image, session=session)
        from engine.repositories.dataset_repository import DatasetRepository

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

    def save_last_batch(self, batch: RenameBatch) -> None:
        record = (
            self.session.query(RenameBatchStateRecord)
            .filter(RenameBatchStateRecord.state_key == self._last_batch_state_key)
            .one_or_none()
        )
        payload = self._batch_to_payload(batch)
        if record is None:
            self.add(
                RenameBatchStateRecord(
                    state_key=self._last_batch_state_key,
                    batch_payload=payload,
                )
            )
        else:
            record.batch_payload = payload
        self.commit()

    def get_last_batch(self) -> RenameBatch | None:
        record = (
            self.session.query(RenameBatchStateRecord)
            .filter(RenameBatchStateRecord.state_key == self._last_batch_state_key)
            .one_or_none()
        )
        if record is None:
            return None
        return self._batch_from_payload(dict(record.batch_payload or {}))

    def clear_last_batch(self) -> None:
        record = (
            self.session.query(RenameBatchStateRecord)
            .filter(RenameBatchStateRecord.state_key == self._last_batch_state_key)
            .one_or_none()
        )
        if record is None:
            return
        self.delete(record)
        self.commit()

    @staticmethod
    def _batch_to_payload(batch: RenameBatch) -> dict[str, object]:
        return {
            "batch_id": batch.batch_id,
            "applied_at": batch.applied_at.astimezone(timezone.utc).isoformat(),
            "entries": [
                {
                    "image_id": entry.image_id,
                    "source_path": str(entry.source_path),
                    "target_path": str(entry.target_path),
                }
                for entry in batch.entries
            ],
        }

    @staticmethod
    def _batch_from_payload(payload: dict[str, object]) -> RenameBatch:
        batch_id = str(payload.get("batch_id", ""))
        entries_payload = payload.get("entries")
        if not batch_id or not isinstance(entries_payload, list):
            raise RuntimeError("Persisted rename batch state is invalid")

        entries: list[RenameBatchEntry] = []
        for item in entries_payload:
            if not isinstance(item, dict):
                raise RuntimeError("Persisted rename batch entry is invalid")
            entries.append(
                RenameBatchEntry(
                    image_id=int(item["image_id"]),
                    source_path=Path(str(item["source_path"])),
                    target_path=Path(str(item["target_path"])),
                )
            )

        return RenameBatch(
            batch_id=batch_id,
            entries=entries,
            applied_at=RenameRepository._as_utc(payload.get("applied_at")),
        )

    @staticmethod
    def _as_utc(value: object) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            raise RuntimeError("Persisted rename batch timestamp is invalid") from None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

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
