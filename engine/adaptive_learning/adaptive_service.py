from __future__ import annotations

from engine.adaptive_learning.adaptive_engine import AdaptiveLearningEngine
from engine.adaptive_learning.adaptive_models import (
    AdaptiveCandidate,
    AdaptiveConfidenceResult,
    AdaptiveEvidence,
    AdaptiveLearningResult,
    AdaptiveUncertaintyItem,
)
from engine.adaptive_learning.adaptive_statistics import AdaptiveLearningStatistics


class AdaptiveLearningService:
    """Service facade for adaptive learning operations."""

    def __init__(self, *, engine: AdaptiveLearningEngine | None = None) -> None:
        self.engine = engine or AdaptiveLearningEngine(callback=self._handle_event)

    def ingest_evidence(self, evidence: AdaptiveEvidence) -> AdaptiveLearningResult:
        return self.engine.ingest_evidence(evidence)

    def incremental_train(self, evidence_items: list[AdaptiveEvidence]) -> AdaptiveLearningResult:
        return self.engine.incremental_train(evidence_items)

    def rollback(self) -> AdaptiveLearningResult:
        return self.engine.rollback()

    def score_candidates(
        self,
        *,
        candidates: list[AdaptiveCandidate],
        series_hint: str | None = None,
    ) -> tuple[list[AdaptiveConfidenceResult], AdaptiveConfidenceResult | None]:
        return self.engine.score_candidates(candidates=candidates, series_hint=series_hint)

    def active_learning_queue(self, *, limit: int = 50) -> list[AdaptiveUncertaintyItem]:
        return self.engine.active_learning_queue(limit=limit)

    def persist(self) -> bytes:
        return self.engine.persist()

    def load(self, payload: bytes | None = None) -> AdaptiveLearningResult:
        return self.engine.load(payload)

    def recover_from_corruption(self) -> AdaptiveLearningResult:
        return self.engine.recover_from_corruption()

    def statistics(self) -> AdaptiveLearningStatistics:
        return self.engine.snapshot_statistics()

    def _handle_event(self, event: object) -> None:
        return None
