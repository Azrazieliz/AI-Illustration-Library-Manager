from __future__ import annotations

from dataclasses import dataclass, field

from engine.recognition.recognition_models import RecognitionCandidate, RecognitionContext
from engine.review.review_models import ReviewDecisionType, ReviewItem, ReviewStatus
from engine.repositories.character_database_repository import CharacterDatabaseRepository


@dataclass(slots=True)
class LearningSignal:
    character_id: int | None
    series_id: int | None
    adjustment: float
    source: str


@dataclass(slots=True)
class RecognitionLearningSnapshot:
    character_adjustments: dict[int, float] = field(default_factory=dict)
    series_adjustments: dict[int, float] = field(default_factory=dict)
    alias_adjustments: dict[str, float] = field(default_factory=dict)
    accepted_corrections: int = 0
    rejected_corrections: int = 0
    review_items_scanned: int = 0


class RecognitionLearningStore:
    """Application-level learning memory for recognition corrections."""

    def __init__(self) -> None:
        self._character_adjustments: dict[int, float] = {}
        self._series_adjustments: dict[int, float] = {}
        self._alias_adjustments: dict[str, float] = {}
        self._accepted = 0
        self._rejected = 0
        self._review_items_scanned = 0

    def snapshot(self) -> RecognitionLearningSnapshot:
        return RecognitionLearningSnapshot(
            character_adjustments=dict(self._character_adjustments),
            series_adjustments=dict(self._series_adjustments),
            alias_adjustments=dict(self._alias_adjustments),
            accepted_corrections=self._accepted,
            rejected_corrections=self._rejected,
            review_items_scanned=self._review_items_scanned,
        )

    def learn_from_review_items(
        self,
        review_items: list[ReviewItem],
        *,
        character_db: CharacterDatabaseRepository,
    ) -> None:
        self._character_adjustments.clear()
        self._series_adjustments.clear()
        self._alias_adjustments.clear()
        self._accepted = 0
        self._rejected = 0
        self._review_items_scanned = 0
        for item in review_items:
            self._review_items_scanned += 1
            self._learn_from_review_item(item, character_db=character_db)

    def _learn_from_review_item(self, item: ReviewItem, *, character_db: CharacterDatabaseRepository) -> None:
        payload = item.proposed_value if isinstance(item.proposed_value, dict) else {}
        candidate_id = payload.get("character_id") if isinstance(payload, dict) else None
        series_id = payload.get("series_id") if isinstance(payload, dict) else None
        alias = payload.get("matched_alias") or payload.get("source_label") or item.character or ""
        adjustment = self._adjustment_for_status(item.status, confidence=float(item.confidence or 0.0))

        if item.status is ReviewStatus.APPROVED:
            self._accepted += 1
            self._apply_adjustment(candidate_id, series_id, alias, adjustment)
        elif item.status is ReviewStatus.REJECTED:
            self._rejected += 1
            self._apply_adjustment(candidate_id, series_id, alias, -adjustment)
        elif item.status is ReviewStatus.SKIPPED:
            self._apply_adjustment(candidate_id, series_id, alias, adjustment * 0.15)

    def _apply_adjustment(self, character_id: int | None, series_id: int | None, alias: str, adjustment: float) -> None:
        if character_id is not None:
            self._character_adjustments[character_id] = self._clamp(self._character_adjustments.get(character_id, 0.0) + adjustment)
        if series_id is not None:
            self._series_adjustments[series_id] = self._clamp(self._series_adjustments.get(series_id, 0.0) + adjustment * 0.5)
        if alias.strip():
            key = alias.strip().casefold()
            self._alias_adjustments[key] = self._clamp(self._alias_adjustments.get(key, 0.0) + adjustment * 0.25)

    def adjustments_for_candidate(self, candidate: RecognitionCandidate) -> float:
        score = 0.0
        if candidate.character_id is not None:
            score += self._character_adjustments.get(candidate.character_id, 0.0)
        if candidate.series_id is not None:
            score += self._series_adjustments.get(candidate.series_id, 0.0) * 0.5
        if candidate.matched_alias:
            score += self._alias_adjustments.get(candidate.matched_alias.casefold(), 0.0) * 0.5
        return self._clamp(score)

    def adjustments_for_context(self, context: RecognitionContext) -> dict[int, float]:
        if not self._character_adjustments:
            return {}
        return dict(self._character_adjustments)

    @staticmethod
    def _adjustment_for_status(status: ReviewStatus, *, confidence: float) -> float:
        base = max(0.05, min(0.2, confidence * 0.2))
        if status is ReviewStatus.APPROVED:
            return base
        if status is ReviewStatus.REJECTED:
            return base
        return base * 0.5

    @staticmethod
    def _clamp(value: float) -> float:
        return max(-0.45, min(0.45, value))
