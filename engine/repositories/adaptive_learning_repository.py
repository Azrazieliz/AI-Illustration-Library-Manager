from __future__ import annotations

from copy import deepcopy

from engine.adaptive_learning.adaptive_builder import AdaptiveLearningBuilder
from engine.adaptive_learning.adaptive_exceptions import (
    AdaptivePersistenceCorruptionError,
    AdaptiveStorageLimitError,
)
from engine.adaptive_learning.adaptive_models import AdaptiveUncertaintyItem, CharacterLearningProfile


MAX_ADAPTIVE_STORAGE_BYTES = 5 * 1024 * 1024 * 1024


class AdaptiveLearningRepository:
    """Repository facade for adaptive-learning profile and uncertainty persistence."""

    def __init__(self, *, builder: AdaptiveLearningBuilder | None = None) -> None:
        self.builder = builder or AdaptiveLearningBuilder()
        self._profiles: dict[str, CharacterLearningProfile] = {}
        self._uncertainty: list[AdaptiveUncertaintyItem] = []
        self._snapshots: list[bytes] = []
        self._persisted_state: bytes = self.builder.serialize_state(profiles={}, uncertainty=[])

    def list_profiles(self) -> dict[str, CharacterLearningProfile]:
        return {key: deepcopy(value) for key, value in self._profiles.items()}

    def list_uncertainty_queue(self) -> list[AdaptiveUncertaintyItem]:
        return [deepcopy(item) for item in self._uncertainty]

    def save_profile(self, key: str, profile: CharacterLearningProfile) -> None:
        self._profiles[key] = deepcopy(profile)

    def delete_profile(self, key: str) -> None:
        if key in self._profiles:
            del self._profiles[key]

    def set_uncertainty_queue(self, queue: list[AdaptiveUncertaintyItem]) -> None:
        self._uncertainty = [deepcopy(item) for item in queue]

    def save_snapshot(self) -> None:
        self._snapshots.append(self.persist())

    def rollback(self) -> bool:
        if not self._snapshots:
            return False
        latest = self._snapshots.pop()
        self.load(latest)
        return True

    def persist(self) -> bytes:
        payload = self.builder.serialize_state(profiles=self._profiles, uncertainty=self._uncertainty)
        if len(payload) > MAX_ADAPTIVE_STORAGE_BYTES:
            raise AdaptiveStorageLimitError(
                f"Adaptive learning persisted payload exceeds 5 GB ({len(payload)} bytes)"
            )
        self._persisted_state = payload
        return payload

    def persisted_size_bytes(self) -> int:
        return len(self._persisted_state)

    def load(self, payload: bytes | None = None) -> None:
        data = self._persisted_state if payload is None else payload
        try:
            profiles, uncertainty = self.builder.deserialize_state(data)
        except Exception as exc:
            raise AdaptivePersistenceCorruptionError("Adaptive state payload is corrupted") from exc
        self._profiles = profiles
        self._uncertainty = uncertainty
        self._persisted_state = data

    def recover_from_corruption(self) -> None:
        self._profiles = {}
        self._uncertainty = []
        self._persisted_state = self.builder.serialize_state(profiles={}, uncertainty=[])
