from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.character_database.character_database_models import CharacterRecord, SeriesRecord
from engine.recognition.recognition_models import RecognitionCandidate, RecognitionContext, RecognitionLabel
from engine.repositories.character_database_repository import CharacterDatabaseRepository


@dataclass(slots=True)
class RankSignal:
    name: str
    weight: float
    value: float


@dataclass(slots=True)
class RankedCandidateSet:
    candidates: list[RecognitionCandidate] = field(default_factory=list)
    unknown_candidate: RecognitionCandidate | None = None
    cache_hit: bool = False
    matching_time_seconds: float = 0.0
    ranking_time_seconds: float = 0.0


class RecognitionRanker:
    """Compute deterministic candidate rankings from multiple signals."""

    def __init__(self, *, threshold: float = 0.78) -> None:
        self.threshold = threshold

    def rank_candidates(
        self,
        *,
        character_db: CharacterDatabaseRepository,
        context: RecognitionContext,
        labels: list[RecognitionLabel],
        learning_adjustments: dict[int, float] | None = None,
        series_candidates: list[SeriesRecord] | None = None,
        metadata_series_names: list[str] | None = None,
        review_series_names: list[str] | None = None,
        filename_hints: list[str] | None = None,
        folder_hints: list[str] | None = None,
    ) -> RankedCandidateSet:
        series_candidates = list(series_candidates or [])
        metadata_series_names = list(metadata_series_names or [])
        review_series_names = list(review_series_names or [])
        filename_hints = list(filename_hints or [])
        folder_hints = list(folder_hints or [])
        learning_adjustments = learning_adjustments or {}

        normalized_labels = [character_db.normalize_text(label.name) for label in labels if label.name.strip()]
        ranked: list[RecognitionCandidate] = []
        for label in labels:
            if not label.name.strip():
                continue
            candidates = character_db.lookup_character_candidates(label.name)
            if not candidates:
                ranked.append(
                    self._build_unknown_candidate(
                        label=label,
                        source_labels=[item.name for item in labels],
                    )
                )
                continue
            for record in candidates:
                ranked.append(
                    self._build_candidate(
                        record=record,
                        label=label,
                        source_labels=[item.name for item in labels],
                        normalized_labels=normalized_labels,
                        learning_adjustments=learning_adjustments,
                        character_db=character_db,
                        series_candidates=series_candidates,
                        metadata_series_names=metadata_series_names,
                        review_series_names=review_series_names,
                        filename_hints=filename_hints,
                        folder_hints=folder_hints,
                    )
                )

        if not ranked:
            ranked = [self._build_unknown_candidate(label=None, source_labels=[item.name for item in labels])]

        ranked.sort(key=lambda item: (-item.confidence, item.unknown, item.character_name, item.character_id or -1))
        for index, item in enumerate(ranked, start=1):
            item.rank = index

        return RankedCandidateSet(
            candidates=ranked,
            unknown_candidate=self._build_unknown_candidate(label=None, source_labels=[item.name for item in labels]),
        )

    def _build_candidate(
        self,
        *,
        record: CharacterRecord,
        label: RecognitionLabel,
        source_labels: list[str],
        normalized_labels: list[str],
        learning_adjustments: dict[int, float],
        character_db: CharacterDatabaseRepository,
        series_candidates: list[SeriesRecord],
        metadata_series_names: list[str],
        review_series_names: list[str],
        filename_hints: list[str],
        folder_hints: list[str],
    ) -> RecognitionCandidate:
        candidate_terms = self._candidate_terms(record, character_db)
        normalized_label = character_db.normalize_text(label.name)
        alias_score = self._alias_quality(normalized_label, candidate_terms)
        series_score = self._series_certainty(record, character_db, series_candidates, metadata_series_names, review_series_names, filename_hints, folder_hints)
        learning_score = self._learning_score(record.character_id, learning_adjustments)
        label_score = max(0.0, min(1.0, label.confidence))
        consistency_score = self._consistency_score(normalized_label, normalized_labels, candidate_terms)
        knowledge_score = 1.0 if normalized_label in candidate_terms else 0.35 + 0.1 * min(len(candidate_terms), 3)

        score_breakdown = {
            "ai": round(label_score, 4),
            "alias": round(alias_score, 4),
            "series": round(series_score, 4),
            "learning": round(learning_score, 4),
            "consistency": round(consistency_score, 4),
            "knowledge": round(min(1.0, knowledge_score), 4),
        }
        confidence = self._combine_scores(score_breakdown)
        return RecognitionCandidate(
            character_id=record.character_id,
            series_id=record.series_id,
            character_name=record.canonical_name,
            series_name=character_db.find_series(record.series_id).canonical_title if record.series_id is not None and character_db.find_series(record.series_id) is not None else None,
            confidence=confidence,
            normalized_label=normalized_label,
            matched_alias=self._best_match(normalized_label, candidate_terms),
            source_labels=source_labels,
            score_breakdown=score_breakdown,
            unknown=False,
        )

    def _build_unknown_candidate(self, *, label: RecognitionLabel | None, source_labels: list[str]) -> RecognitionCandidate:
        confidence = 0.0 if label is None else max(0.01, round(label.confidence * 0.08, 4))
        return RecognitionCandidate(
            character_id=None,
            series_id=None,
            character_name="Unknown",
            series_name=None,
            confidence=confidence,
            normalized_label=label.name if label is not None else "",
            matched_alias="",
            source_labels=source_labels,
            score_breakdown={"ai": confidence, "alias": 0.0, "series": 0.0, "learning": 0.0, "consistency": 0.0, "knowledge": 0.0},
            unknown=True,
        )

    def _candidate_terms(self, record: CharacterRecord, character_db: CharacterDatabaseRepository) -> list[str]:
        terms = [character_db.normalize_text(record.canonical_name)]
        terms.extend(character_db.normalize_text(alias) for alias in record.aliases)
        terms.extend(character_db.normalize_text(alias) for alias in record.localized_names)
        if record.japanese_name:
            terms.append(character_db.normalize_text(record.japanese_name))
        if record.english_name:
            terms.append(character_db.normalize_text(record.english_name))
        if record.romaji:
            terms.append(character_db.normalize_text(record.romaji))
        terms.extend(character_db.normalize_text(alias) for alias in record.nicknames)
        terms.extend(character_db.normalize_text(alias) for alias in record.alternative_spellings)
        terms.extend(character_db.normalize_text(alias) for alias in record.abbreviations)
        return [term for term in terms if term]

    def _alias_quality(self, normalized_label: str, candidate_terms: list[str]) -> float:
        if not normalized_label or not candidate_terms:
            return 0.0
        if normalized_label in candidate_terms:
            return 1.0
        if any(normalized_label == term for term in candidate_terms):
            return 0.98
        distances = [self._token_overlap(normalized_label, term) for term in candidate_terms]
        return max(distances, default=0.0)

    def _series_certainty(
        self,
        record: CharacterRecord,
        character_db: CharacterDatabaseRepository,
        series_candidates: list[SeriesRecord],
        metadata_series_names: list[str],
        review_series_names: list[str],
        filename_hints: list[str],
        folder_hints: list[str],
    ) -> float:
        if record.series_id is None:
            return 0.25

        series = character_db.find_series(record.series_id)
        if series is None:
            return 0.15

        series_terms = [character_db.normalize_text(series.canonical_title)]
        series_terms.extend(character_db.normalize_text(alias) for alias in series.aliases)
        if series.japanese_title:
            series_terms.append(character_db.normalize_text(series.japanese_title))
        if series.english_title:
            series_terms.append(character_db.normalize_text(series.english_title))
        if series.romaji:
            series_terms.append(character_db.normalize_text(series.romaji))
        if series.franchise:
            series_terms.append(character_db.normalize_text(series.franchise))
        series_terms = [term for term in series_terms if term]

        candidate_score = 0.3
        for item in series_candidates:
            if item.series_id == record.series_id:
                candidate_score = 1.0
                break
        else:
            for hint in metadata_series_names + review_series_names + filename_hints + folder_hints:
                normalized = character_db.normalize_text(hint)
                if normalized and any(normalized == term or normalized in term or term in normalized for term in series_terms):
                    candidate_score = max(candidate_score, 0.95)
        return candidate_score

    def _learning_score(self, character_id: int, adjustments: dict[int, float]) -> float:
        if character_id not in adjustments:
            return 0.5
        return max(0.0, min(1.0, 0.5 + adjustments[character_id]))

    def _consistency_score(self, normalized_label: str, normalized_labels: list[str], candidate_terms: list[str]) -> float:
        if not normalized_labels:
            return 0.25
        if normalized_label in normalized_labels:
            return 1.0
        overlaps = [self._token_overlap(label, term) for label in normalized_labels for term in candidate_terms]
        return max(overlaps, default=0.0)

    def _combine_scores(self, score_breakdown: dict[str, float]) -> float:
        weights = {
            "ai": 0.32,
            "alias": 0.24,
            "series": 0.18,
            "learning": 0.10,
            "consistency": 0.08,
            "knowledge": 0.08,
        }
        total = sum(score_breakdown[key] * weights[key] for key in weights)
        # Leave headroom so later canonical boosts can still raise confidence.
        tempered = total * 0.8
        return round(max(0.0, min(1.0, tempered)), 4)

    @staticmethod
    def _best_match(normalized_label: str, candidate_terms: list[str]) -> str:
        if normalized_label in candidate_terms:
            return normalized_label
        best = ""
        best_score = 0.0
        for term in candidate_terms:
            score = RecognitionRanker._token_overlap(normalized_label, term)
            if score > best_score:
                best = term
                best_score = score
        return best

    @staticmethod
    def _token_overlap(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return round(overlap / float(union), 4) if union else 0.0
