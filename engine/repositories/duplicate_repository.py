from __future__ import annotations

from typing import Any

from engine.database.models.duplicate import DuplicateRecord
from engine.repositories.base_repository import BaseRepository


class DuplicateRepository(BaseRepository[DuplicateRecord]):
    """Repository for :class:`~engine.database.models.duplicate.DuplicateRecord`."""

    def __init__(self) -> None:
        super().__init__(DuplicateRecord)

    def get_by_pair(self, image_a_id: int, image_b_id: int) -> DuplicateRecord | None:
        """Return the record for an ordered (a, b) pair, or ``None``."""
        return (
            self.session.query(DuplicateRecord)
            .filter(
                DuplicateRecord.image_a_id == image_a_id,
                DuplicateRecord.image_b_id == image_b_id,
            )
            .first()
        )

    def get_canonical(self, id_x: int, id_y: int) -> DuplicateRecord | None:
        """Return the record for a pair regardless of insertion order.

        Checks both ``(x, y)`` and ``(y, x)`` orderings.
        """
        return (
            self.session.query(DuplicateRecord)
            .filter(
                (
                    (DuplicateRecord.image_a_id == id_x)
                    & (DuplicateRecord.image_b_id == id_y)
                )
                | (
                    (DuplicateRecord.image_a_id == id_y)
                    & (DuplicateRecord.image_b_id == id_x)
                )
            )
            .first()
        )

    def create_duplicate(
        self,
        *,
        image_a_id: int,
        image_b_id: int,
        match_type: str,
        confidence: str,
        sha256_match: bool,
        phash_distance: int | None,
        ahash_distance: int | None,
        dhash_distance: int | None,
        overall_score: float,
        status: str = "pending",
    ) -> DuplicateRecord:
        record = DuplicateRecord(
            image_a_id=image_a_id,
            image_b_id=image_b_id,
            match_type=match_type,
            confidence=confidence,
            sha256_match=sha256_match,
            phash_distance=phash_distance,
            ahash_distance=ahash_distance,
            dhash_distance=dhash_distance,
            overall_score=overall_score,
            status=status,
        )
        self.add(record)
        self.commit()
        return record

    def update_duplicate(self, record: DuplicateRecord, **changes: Any) -> DuplicateRecord:
        for key, value in changes.items():
            setattr(record, key, value)
        self.commit()
        return record

    def mark_reviewed(self, record: DuplicateRecord) -> DuplicateRecord:
        return self.update_duplicate(record, status="reviewed")

    def mark_rejected(self, record: DuplicateRecord) -> DuplicateRecord:
        return self.update_duplicate(record, status="rejected")

    def list_pending(self) -> list[DuplicateRecord]:
        return list(
            self.session.query(DuplicateRecord)
            .filter(DuplicateRecord.status == "pending")
            .all()
        )

    def list_by_image(self, image_id: int) -> list[DuplicateRecord]:
        return list(
            self.session.query(DuplicateRecord)
            .filter(
                (DuplicateRecord.image_a_id == image_id)
                | (DuplicateRecord.image_b_id == image_id)
            )
            .all()
        )

    def list_all_duplicates(self) -> list[DuplicateRecord]:
        return list(self.session.query(DuplicateRecord).all())

    def delete_duplicate(self, record: DuplicateRecord) -> None:
        self.delete(record)
        self.commit()
