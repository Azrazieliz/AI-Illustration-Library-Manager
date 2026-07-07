from __future__ import annotations

from typing import Any

from engine.database.models.hash import HashModel
from engine.repositories.base_repository import BaseRepository


class HashRepository(BaseRepository[HashModel]):
    """Repository for :class:`~engine.database.models.hash.HashModel` records."""

    def __init__(self) -> None:
        super().__init__(HashModel)

    def get_by_image_id(self, image_id: int) -> HashModel | None:
        return (
            self.session.query(HashModel)
            .filter(HashModel.image_id == image_id)
            .first()
        )

    def get_by_sha256(self, sha256: str) -> list[HashModel]:
        """Return all hash records that share the given SHA-256 value."""
        return list(
            self.session.query(HashModel)
            .filter(HashModel.sha256 == sha256)
            .all()
        )

    def create_hash_record(
        self,
        *,
        image_id: int,
        sha256: str,
        phash: str | None = None,
        ahash: str | None = None,
        dhash: str | None = None,
    ) -> HashModel:
        record = HashModel(
            image_id=image_id,
            sha256=sha256,
            phash=phash,
            ahash=ahash,
            dhash=dhash,
        )
        self.add(record)
        self.commit()
        return record

    def update_hash_record(self, record: HashModel, **changes: Any) -> HashModel:
        for key, value in changes.items():
            setattr(record, key, value)
        self.commit()
        return record

    def delete_hash_record(self, record: HashModel) -> None:
        self.delete(record)
        self.commit()

    def list_all_hashes(self) -> list[HashModel]:
        return list(self.session.query(HashModel).all())
