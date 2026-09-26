from __future__ import annotations

from base64 import b64decode, b64encode
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from sqlalchemy import delete, select, update

from engine.adaptive_learning.adaptive_builder import AdaptiveLearningBuilder
from engine.adaptive_learning.adaptive_exceptions import AdaptivePersistenceCorruptionError
from engine.adaptive_learning.adaptive_models import AdaptiveUncertaintyItem, CharacterLearningProfile
from engine.database.models.adaptive_learning_state import AdaptiveLearningStateRecord
from engine.database.session import session_scope
from engine.repositories.adaptive_learning_repository import InMemoryAdaptiveLearningRepository


class DurableAdaptiveLearningRepository(InMemoryAdaptiveLearningRepository):
    """Versioned persistence for adaptive profiles, uncertainty, and rollback snapshots."""

    _state_key = "default"
    _state_lock = RLock()

    def __init__(self, *, builder: AdaptiveLearningBuilder | None = None) -> None:
        super().__init__(builder=builder)
        self._lock = self._state_lock
        self._state_version: int | None = None
        self._load_state()

    @classmethod
    def reset_state(cls) -> None:
        with cls._state_lock, session_scope() as session:
            session.execute(delete(AdaptiveLearningStateRecord))

    def save_profile(self, key: str, profile: CharacterLearningProfile) -> None:
        with self._lock:
            super().save_profile(key, profile)
            self.persist()

    def delete_profile(self, key: str) -> None:
        with self._lock:
            super().delete_profile(key)
            self.persist()

    def set_uncertainty_queue(self, queue: list[AdaptiveUncertaintyItem]) -> None:
        with self._lock:
            super().set_uncertainty_queue(queue)
            self.persist()

    def persist(self) -> bytes:
        with self._lock:
            payload = super().persist()
            self._persist_state()
            return payload

    def load(self, payload: bytes | None = None) -> None:
        with self._lock:
            super().load(payload)
            self._persist_state()

    def recover_from_corruption(self) -> None:
        with self._lock:
            super().recover_from_corruption()
            self._snapshots = []
            self._persist_state()

    def _load_state(self) -> None:
        with self._lock, session_scope() as session:
            row = session.scalar(
                select(AdaptiveLearningStateRecord).where(
                    AdaptiveLearningStateRecord.state_key == self._state_key
                )
            )
            if row is None:
                return
            self._state_version = row.version
            self._restore_state(dict(row.state_payload or {}))

    def _persist_state(self) -> None:
        payload = self._state_payload()
        with session_scope() as session:
            row = session.scalar(
                select(AdaptiveLearningStateRecord).where(
                    AdaptiveLearningStateRecord.state_key == self._state_key
                )
            )
            if row is None:
                if self._state_version is not None:
                    raise RuntimeError("Adaptive-learning state was removed while this repository was active")
                row = AdaptiveLearningStateRecord(state_key=self._state_key, state_payload=payload)
                session.add(row)
                session.flush()
                self._state_version = row.version
                return
            if self._state_version is None or row.version != self._state_version:
                raise RuntimeError("Adaptive-learning state changed in another repository instance; reload before writing")
            result = session.execute(
                update(AdaptiveLearningStateRecord)
                .where(
                    AdaptiveLearningStateRecord.id == row.id,
                    AdaptiveLearningStateRecord.version == self._state_version,
                )
                .values(
                    state_payload=payload,
                    version=AdaptiveLearningStateRecord.version + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if int(result.rowcount or 0) != 1:
                raise RuntimeError("Adaptive-learning state changed concurrently; retry the operation")
            self._state_version += 1

    def _state_payload(self) -> dict[str, Any]:
        return {
            "persisted_state": self._encode(self._persisted_state),
            "snapshots": [self._encode(snapshot) for snapshot in self._snapshots],
        }

    def _restore_state(self, payload: dict[str, Any]) -> None:
        persisted_state = self._decode(payload.get("persisted_state"))
        snapshots = payload.get("snapshots", [])
        if not isinstance(snapshots, list):
            raise AdaptivePersistenceCorruptionError("Adaptive state payload is corrupted")
        restored_snapshots = [self._decode(snapshot) for snapshot in snapshots]
        super().load(persisted_state)
        self._snapshots = restored_snapshots

    @staticmethod
    def _encode(payload: bytes) -> str:
        return b64encode(payload).decode("ascii")

    @staticmethod
    def _decode(payload: Any) -> bytes:
        if not isinstance(payload, str):
            raise AdaptivePersistenceCorruptionError("Adaptive state payload is corrupted")
        try:
            return b64decode(payload.encode("ascii"), validate=True)
        except (TypeError, ValueError) as exc:
            raise AdaptivePersistenceCorruptionError("Adaptive state payload is corrupted") from exc