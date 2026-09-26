from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from engine.database.models.export_artifact import ExportArtifactRecord
from engine.database.models.image import Image
from engine.database.session import session_scope
from engine.dataset.dataset_builder import DatasetBuilder
from engine.dataset.dataset_models import DatasetEntry
from engine.export.export_models import ExportFormatType, ExportRecord
from engine.repositories.base_repository import BaseRepository
from engine.repositories.dataset_repository import DatasetRepository


class ExportRepository(BaseRepository[Image]):
    """Repository supplying dataset data and durable export artifact metadata."""

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(Image, session=session)

    @classmethod
    def reset_state(cls) -> None:
        with session_scope() as session:
            session.execute(delete(ExportArtifactRecord))

    def get_image_by_path(self, path: str | Path) -> Image | None:
        return self.session.query(Image).filter(Image.original_path == str(path)).first()

    def build_dataset_entry(self, path: str | Path, *, semantic: dict | None = None) -> DatasetEntry | None:
        dataset_repository = DatasetRepository()
        return DatasetBuilder(dataset_repository).build(path, semantic=semantic)

    def upsert_export_record(self, record: ExportRecord) -> bool:
        with session_scope() as session:
            row, created = self._get_or_create(session, record.format_type.value, record.image_id)
            row.path = str(record.path)
            row.payload = dict(record.payload)
            row.caption = record.caption
            row.tags = list(record.tags)
            row.provenance = list(record.provenance)
            row.exported_at = record.exported_at
            row.updated_at = datetime.now(timezone.utc)
            return created

    def get_export_record(self, *, format_type: ExportFormatType, image_id: int) -> ExportRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(ExportArtifactRecord).where(
                    ExportArtifactRecord.format_type == format_type.value,
                    ExportArtifactRecord.image_id == image_id,
                )
            )
            return None if row is None or row.path is None else self._to_export_record(row)

    def list_export_records(self, *, format_type: ExportFormatType | None = None) -> list[ExportRecord]:
        with session_scope() as session:
            statement = select(ExportArtifactRecord).order_by(ExportArtifactRecord.format_type, ExportArtifactRecord.image_id)
            if format_type is not None:
                statement = statement.where(ExportArtifactRecord.format_type == format_type.value)
            rows = list(session.scalars(statement))
            return [self._to_export_record(row) for row in rows if row.path is not None]

    def save_export_manifest(
        self,
        *,
        format_type: ExportFormatType | str,
        image_id: int,
        manifest: dict,
    ) -> None:
        with session_scope() as session:
            row, _ = self._get_or_create(session, self._format_value(format_type), image_id)
            row.payload = dict(manifest)
            row.updated_at = datetime.now(timezone.utc)

    def get_export_manifest(self, *, format_type: ExportFormatType | str, image_id: int) -> dict:
        with session_scope() as session:
            row = session.scalar(
                select(ExportArtifactRecord).where(
                    ExportArtifactRecord.format_type == self._format_value(format_type),
                    ExportArtifactRecord.image_id == image_id,
                )
            )
            return {} if row is None else dict(row.payload or {})

    def clear_export_manifest(self, *, format_type: ExportFormatType | str, image_id: int) -> bool:
        with session_scope() as session:
            row = session.scalar(
                select(ExportArtifactRecord).where(
                    ExportArtifactRecord.format_type == self._format_value(format_type),
                    ExportArtifactRecord.image_id == image_id,
                )
            )
            if row is None:
                return False
            row.payload = {}
            row.updated_at = datetime.now(timezone.utc)
            return True

    def save_export_provenance(
        self,
        *,
        format_type: ExportFormatType | str,
        image_id: int,
        provenance: list[str],
    ) -> None:
        if any(not isinstance(item, str) for item in provenance):
            raise ValueError("Export provenance must contain only strings")
        with session_scope() as session:
            row, _ = self._get_or_create(session, self._format_value(format_type), image_id)
            row.provenance = list(provenance)
            row.updated_at = datetime.now(timezone.utc)

    def get_export_provenance(self, *, format_type: ExportFormatType | str, image_id: int) -> list[str]:
        with session_scope() as session:
            row = session.scalar(
                select(ExportArtifactRecord).where(
                    ExportArtifactRecord.format_type == self._format_value(format_type),
                    ExportArtifactRecord.image_id == image_id,
                )
            )
            return [] if row is None else list(row.provenance or [])

    def list_export_state(self) -> list[tuple[str, int, dict, list[str]]]:
        with session_scope() as session:
            rows = list(session.scalars(select(ExportArtifactRecord).order_by(ExportArtifactRecord.format_type, ExportArtifactRecord.image_id)))
            return [
                (row.format_type, row.image_id, dict(row.payload or {}), list(row.provenance or []))
                for row in rows
            ]

    def list_exported_image_ids(self, *, format_type: ExportFormatType | str) -> list[int]:
        value = self._format_value(format_type)
        with session_scope() as session:
            return list(
                session.scalars(
                    select(ExportArtifactRecord.image_id)
                    .where(ExportArtifactRecord.format_type == value)
                    .order_by(ExportArtifactRecord.image_id)
                )
            )

    def count_exports(self, *, format_type: ExportFormatType | str) -> int:
        return len(self.list_exported_image_ids(format_type=format_type))

    @staticmethod
    def _format_value(format_type: ExportFormatType | str) -> str:
        return format_type.value if isinstance(format_type, ExportFormatType) else str(format_type)

    @staticmethod
    def _get_or_create(session: Session, format_type: str, image_id: int) -> tuple[ExportArtifactRecord, bool]:
        row = session.scalar(
            select(ExportArtifactRecord).where(
                ExportArtifactRecord.format_type == format_type,
                ExportArtifactRecord.image_id == image_id,
            )
        )
        if row is not None:
            return row, False
        row = ExportArtifactRecord(format_type=format_type, image_id=image_id, payload={}, tags=[], provenance=[])
        session.add(row)
        return row, True

    @staticmethod
    def _to_export_record(row: ExportArtifactRecord) -> ExportRecord:
        exported_at = row.exported_at or row.created_at
        if exported_at.tzinfo is None:
            exported_at = exported_at.replace(tzinfo=timezone.utc)
        updated_at = row.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return ExportRecord(
            image_id=row.image_id,
            path=Path(row.path or ""),
            format_type=ExportFormatType(row.format_type),
            payload=dict(row.payload or {}),
            caption=row.caption or "",
            tags=list(row.tags or []),
            provenance=list(row.provenance or []),
            exported_at=exported_at,
            updated_at=updated_at,
        )