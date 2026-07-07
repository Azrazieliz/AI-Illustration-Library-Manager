from __future__ import annotations

from dataclasses import dataclass, field

from engine.character_database.character_database_models import CharacterRecord, SeriesRecord
from engine.recognition.recognition_models import RecognitionCandidate, RecognitionContext
from engine.repositories.character_database_repository import CharacterDatabaseRepository


@dataclass(slots=True)
class DisambiguationResult:
    candidates: list[RecognitionCandidate] = field(default_factory=list)
    primary_series_id: int | None = None
    primary_series_name: str | None = None


class RecognitionDisambiguator:
    """Deterministic disambiguation across same-name candidates."""

    def disambiguate(
        self,
        *,
        candidate: RecognitionCandidate,
        character_db: CharacterDatabaseRepository,
        context: RecognitionContext,
        series_candidates: list[SeriesRecord],
        review_series_names: list[str],
        metadata_series_names: list[str],
    ) -> RecognitionCandidate:
        if candidate.character_id is None:
            return candidate

        record = character_db.find_character(candidate.character_id)
        if record is None:
            return candidate

        series_boost = self._series_boost(record, character_db, context, series_candidates, review_series_names, metadata_series_names)
        relationship_boost = self._relationship_boost(record, character_db, context)
        final_confidence = max(0.0, min(1.0, round(candidate.confidence + series_boost + relationship_boost, 4)))
        adjusted = RecognitionCandidate(
            character_id=candidate.character_id,
            series_id=candidate.series_id,
            character_name=candidate.character_name,
            series_name=candidate.series_name,
            confidence=final_confidence,
            normalized_label=candidate.normalized_label,
            matched_alias=candidate.matched_alias,
            source_labels=list(candidate.source_labels),
            score_breakdown=dict(candidate.score_breakdown),
            rank=candidate.rank,
            unknown=candidate.unknown,
        )
        adjusted.score_breakdown["series_boost"] = round(series_boost, 4)
        adjusted.score_breakdown["relationship_boost"] = round(relationship_boost, 4)
        return adjusted

    def rank(
        self,
        candidates: list[RecognitionCandidate],
        *,
        character_db: CharacterDatabaseRepository,
        context: RecognitionContext,
        series_candidates: list[SeriesRecord],
        review_series_names: list[str],
        metadata_series_names: list[str],
    ) -> list[RecognitionCandidate]:
        ranked = [
            self.disambiguate(
                candidate=item,
                character_db=character_db,
                context=context,
                series_candidates=series_candidates,
                review_series_names=review_series_names,
                metadata_series_names=metadata_series_names,
            )
            for item in candidates
        ]
        ranked.sort(key=lambda item: (-item.confidence, item.unknown, item.character_name, item.character_id or -1))
        for index, item in enumerate(ranked, start=1):
            item.rank = index
        return ranked

    def _series_boost(
        self,
        record: CharacterRecord,
        character_db: CharacterDatabaseRepository,
        context: RecognitionContext,
        series_candidates: list[SeriesRecord],
        review_series_names: list[str],
        metadata_series_names: list[str],
    ) -> float:
        if record.series_id is None:
            return 0.0
        series = character_db.find_series(record.series_id)
        if series is None:
            return 0.0

        series_terms = character_db._all_series_values(series) if hasattr(character_db, "_all_series_values") else [series.canonical_title]
        hint_values = [context.ai_series_name, context.current_series_name, context.folder_name, context.filename] + list(review_series_names) + list(metadata_series_names)
        if series_candidates and any(item.series_id == record.series_id for item in series_candidates):
            return 0.18
        for hint in hint_values:
            normalized = character_db.normalize_text(hint or "")
            if normalized and any(normalized == character_db.normalize_text(term) or normalized in character_db.normalize_text(term) for term in series_terms):
                return 0.22
        return 0.05 if context.current_series_id == record.series_id else 0.0

    def _relationship_boost(self, record: CharacterRecord, character_db: CharacterDatabaseRepository, context: RecognitionContext) -> float:
        if record.series_id is None:
            return 0.0
        linked_names = {character_db.normalize_text(value) for value in character_db.series_titles_for_character(record.character_id)}
        context_names = {
            character_db.normalize_text(context.filename),
            character_db.normalize_text(context.folder_name),
            character_db.normalize_text(context.current_series_name or ""),
            character_db.normalize_text(context.ai_series_name or ""),
        }
        if linked_names & context_names:
            return 0.08
        return 0.0
