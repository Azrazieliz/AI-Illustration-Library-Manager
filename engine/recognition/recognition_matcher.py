from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from engine.character_database.character_database_models import CharacterRecord, SeriesRecord
from engine.database.models.image import Image
from engine.recognition.recognition_disambiguation import RecognitionDisambiguator
from engine.recognition.recognition_learning import RecognitionLearningStore
from engine.recognition.recognition_models import (
    RecognitionAssignment,
    RecognitionCandidate,
    RecognitionContext,
    RecognitionLabel,
    RecognitionOutput,
)
from engine.recognition.recognition_ranking import RecognitionRanker, RankedCandidateSet
from engine.repositories.recognition_repository import RecognitionRepository
from engine.repositories.character_database_repository import CharacterDatabaseRepository


@dataclass(slots=True)
class RecognitionMatchResult:
    assignment: RecognitionAssignment
    candidates: list[RecognitionCandidate]
    cache_hit: bool
    matching_time_seconds: float
    ranking_time_seconds: float
    series_candidates: list[SeriesRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    review_item_id: int | None = None


class RecognitionMatcher:
    """Canonical recognition matcher backed by the character knowledge database."""

    def __init__(
        self,
        *,
        recognition_repository: RecognitionRepository,
        character_db: CharacterDatabaseRepository,
        learning_store: RecognitionLearningStore | None = None,
        ranker: RecognitionRanker | None = None,
        disambiguator: RecognitionDisambiguator | None = None,
        auto_assign_threshold: float = 0.82,
    ) -> None:
        self.recognition_repository = recognition_repository
        self.character_db = character_db
        self.learning_store = learning_store or RecognitionLearningStore()
        self.ranker = ranker or RecognitionRanker(threshold=auto_assign_threshold)
        self.disambiguator = disambiguator or RecognitionDisambiguator()
        self.auto_assign_threshold = auto_assign_threshold
        self._cache: dict[str, RecognitionMatchResult] = {}

    def match(self, *, image: Image, output: RecognitionOutput, path: Path) -> RecognitionMatchResult:
        cache_key = self._build_cache_key(image=image, output=output, path=path)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return self._clone(cached, cache_hit=True)

        matching_started = perf_counter()
        context = self.recognition_repository.build_context(image=image, output=output, path=path)
        review_items = self.recognition_repository.review_repository.list_review_items()
        self.learning_store.learn_from_review_items(review_items, character_db=self.character_db)
        learning_adjustments = self.learning_store.adjustments_for_context(context)
        metadata_series_names = self.recognition_repository.metadata_series_names(image=image)
        review_series_names = self.recognition_repository.review_series_names(image=image)
        filename_hints = self.recognition_repository.filename_hints(context=context)
        folder_hints = self.recognition_repository.folder_hints(context=context)
        series_candidates = self._series_candidates(output=output, context=context, filename_hints=filename_hints, folder_hints=folder_hints, metadata_series_names=metadata_series_names, review_series_names=review_series_names)
        matching_time = perf_counter() - matching_started

        ranking_started = perf_counter()
        ranked_set = self.ranker.rank_candidates(
            character_db=self.character_db,
            context=context,
            labels=self._labels_for_output(output),
            learning_adjustments=learning_adjustments,
            series_candidates=series_candidates,
            metadata_series_names=metadata_series_names,
            review_series_names=review_series_names,
            filename_hints=filename_hints,
            folder_hints=folder_hints,
        )
        ranked = self.disambiguator.rank(
            ranked_set.candidates,
            character_db=self.character_db,
            context=context,
            series_candidates=series_candidates,
            review_series_names=review_series_names,
            metadata_series_names=metadata_series_names,
        )
        ranking_time = perf_counter() - ranking_started

        assignment = self._finalize_assignment(
            image=image,
            output=output,
            context=context,
            ranked_candidates=ranked,
            series_candidates=series_candidates,
            metadata_series_names=metadata_series_names,
            review_series_names=review_series_names,
            filename_hints=filename_hints,
            folder_hints=folder_hints,
            learning_adjustments=learning_adjustments,
        )
        result = RecognitionMatchResult(
            assignment=assignment,
            candidates=ranked,
            cache_hit=False,
            matching_time_seconds=matching_time,
            ranking_time_seconds=ranking_time,
            series_candidates=series_candidates,
            metadata={
                "filename_hints": filename_hints,
                "folder_hints": folder_hints,
                "metadata_series_names": metadata_series_names,
                "review_series_names": review_series_names,
            },
            review_item_id=assignment.review_item_id,
        )
        self._cache[cache_key] = self._clone(result, cache_hit=False)
        return result

    def _finalize_assignment(
        self,
        *,
        image: Image,
        output: RecognitionOutput,
        context: RecognitionContext,
        ranked_candidates: list[RecognitionCandidate],
        series_candidates: list[SeriesRecord],
        metadata_series_names: list[str],
        review_series_names: list[str],
        filename_hints: list[str],
        folder_hints: list[str],
        learning_adjustments: dict[int, float],
    ) -> RecognitionAssignment:
        if not ranked_candidates:
            return RecognitionAssignment(
                character_id=None,
                series_id=None,
                character_name=None,
                series_name=None,
                confidence=0.0,
                auto_assigned=False,
                needs_review=True,
                reason="No candidate characters matched.",
                candidates=[],
                source_labels=self._labels_for_output(output),
                metadata={"unknown": True},
            )

        top = ranked_candidates[0]
        if top.unknown:
            return self._unknown_assignment(
                image=image,
                output=output,
                ranked_candidates=ranked_candidates,
            )

        series_name = (
            top.series_name
            or self._series_name_from_candidates(series_candidates, top.series_id)
            or (output.series.name if output.series is not None else None)
        )
        final_confidence = self._normalize_confidence(top.confidence, context=context, output=output, series_name=series_name, filename_hints=filename_hints, folder_hints=folder_hints, metadata_series_names=metadata_series_names, review_series_names=review_series_names)
        ambiguous_same_name = sum(
            1 for item in ranked_candidates if not item.unknown and item.character_name == top.character_name
        ) > 1
        normalized_series_name = self.character_db.normalize_text(series_name or "")
        series_context_hints = [
            context.current_series_name,
            output.series.name if output.series is not None else None,
            *filename_hints,
            *folder_hints,
            *metadata_series_names,
            *review_series_names,
        ]
        matching_series_hint = any(
            normalized_series_name
            and self.character_db.normalize_text(hint or "") == normalized_series_name
            for hint in series_context_hints
        )
        learned_support = top.character_id is not None and learning_adjustments.get(top.character_id, 0.0) > 0.0
        needs_review = final_confidence < self.auto_assign_threshold or (ambiguous_same_name and not (matching_series_hint or learned_support))
        auto_assigned = not needs_review
        if auto_assigned:
            reason = "Auto-assigned canonical character."
        elif ambiguous_same_name and not (matching_series_hint or learned_support):
            reason = "Ambiguous same-name match requires review."
        else:
            reason = "Confidence below auto-assign threshold."
        reported_confidence = final_confidence if auto_assigned else top.confidence
        review_item_id = None

        if needs_review:
            review_item = self.recognition_repository.create_review_item(
                image=image,
                assignment={
                    "character_id": top.character_id,
                    "series_id": top.series_id,
                    "character_name": top.character_name,
                    "series_name": series_name,
                    "confidence": final_confidence,
                    "matched_alias": top.matched_alias,
                    "source_labels": [label.name for label in self._labels_for_output(output)],
                    "score_breakdown": dict(top.score_breakdown),
                },
                output=output,
                reason=reason,
                review_series_name=series_name,
                review_character_name=top.character_name,
            )
            review_item_id = review_item.review_id
            self.learning_store._review_items_scanned += 1
        else:
            self.learning_store._accepted += 1
            if top.character_id is not None:
                self.learning_store._character_adjustments[top.character_id] = self.learning_store._clamp(self.learning_store._character_adjustments.get(top.character_id, 0.0) + 0.01)

        return RecognitionAssignment(
            character_id=top.character_id,
            series_id=top.series_id,
            character_name=top.character_name,
            series_name=series_name,
            confidence=reported_confidence,
            auto_assigned=auto_assigned,
            needs_review=needs_review,
            reason=reason,
            candidates=ranked_candidates,
            source_labels=self._labels_for_output(output),
            metadata={
                "image_id": image.id,
                "path": str(context.path),
                "model_name": output.model_name,
                "model_version": output.model_version,
                "provider_name": output.provider_name,
                "filename_hints": filename_hints,
                "folder_hints": folder_hints,
                "metadata_series_names": metadata_series_names,
                "review_series_names": review_series_names,
                "score_breakdown": dict(top.score_breakdown),
            },
            review_item_id=review_item_id,
        )

    def _unknown_assignment(self, *, image: Image, output: RecognitionOutput, ranked_candidates: list[RecognitionCandidate]) -> RecognitionAssignment:
        unknown = next((item for item in ranked_candidates if item.unknown), None)
        confidence = unknown.confidence if unknown is not None else 0.0
        review_item = self.recognition_repository.create_review_item(
            image=image,
            assignment={
                "character_id": None,
                "series_id": None,
                "character_name": None,
                "series_name": output.series.name if output.series is not None else None,
                "matched_alias": "",
                "source_labels": [label.name for label in self._labels_for_output(output)],
                "score_breakdown": unknown.score_breakdown if unknown is not None else {},
                "confidence": confidence,
            },
            output=output,
            reason="Unknown character.",
            review_series_name=output.series.name if output.series is not None else None,
            review_character_name=None,
        )
        return RecognitionAssignment(
            character_id=None,
            series_id=None,
            character_name=None,
            series_name=output.series.name if output.series is not None else None,
            confidence=confidence,
            auto_assigned=False,
            needs_review=True,
            reason="Unknown character.",
            candidates=ranked_candidates,
            source_labels=self._labels_for_output(output),
            metadata={"unknown": True},
            review_item_id=review_item.review_id,
        )

    def _series_candidates(
        self,
        *,
        output: RecognitionOutput,
        context: RecognitionContext,
        filename_hints: list[str],
        folder_hints: list[str],
        metadata_series_names: list[str],
        review_series_names: list[str],
    ) -> list[SeriesRecord]:
        names: list[str] = []
        if output.series is not None and output.series.name.strip():
            names.append(output.series.name)
        names.extend(filename_hints)
        names.extend(folder_hints)
        names.extend(metadata_series_names)
        names.extend(review_series_names)
        if context.current_series_name:
            names.append(context.current_series_name)

        series_records: dict[int, SeriesRecord] = {}
        for name in names:
            for record in self.character_db.lookup_series_candidates(name):
                series_records[record.series_id] = record
        return sorted(series_records.values(), key=lambda item: item.series_id)

    def _normalize_confidence(
        self,
        confidence: float,
        *,
        context: RecognitionContext,
        output: RecognitionOutput,
        series_name: str | None,
        filename_hints: list[str],
        folder_hints: list[str],
        metadata_series_names: list[str],
        review_series_names: list[str],
    ) -> float:
        normalized = confidence
        if output.series is not None and series_name:
            normalized += 0.04
        if any(self.character_db.normalize_text(hint) in self.character_db.normalize_text(context.filename) for hint in filename_hints if hint):
            normalized += 0.03
        if any(self.character_db.normalize_text(hint) in self.character_db.normalize_text(context.folder_name) for hint in folder_hints if hint):
            normalized += 0.03
        if context.current_series_name and series_name and self.character_db.normalize_text(context.current_series_name) == self.character_db.normalize_text(series_name):
            normalized += 0.05
        if any(self.character_db.normalize_text(name) == self.character_db.normalize_text(series_name or "") for name in metadata_series_names + review_series_names if name):
            normalized += 0.04
        return max(0.0, min(1.0, round(normalized, 4)))

    def _labels_for_output(self, output: RecognitionOutput) -> list[RecognitionLabel]:
        if output.characters:
            return list(output.characters)
        return [RecognitionLabel(name=item.name, confidence=item.confidence) for item in output.character_candidates]

    def _series_name_from_candidates(self, series_candidates: list[SeriesRecord], series_id: int | None) -> str | None:
        if series_id is None:
            return None
        for record in series_candidates:
            if record.series_id == series_id:
                return record.canonical_title
        return None

    def _build_cache_key(self, *, image: Image, output: RecognitionOutput, path: Path) -> str:
        snapshot = self.learning_store.snapshot()
        return "|".join(
            [
                str(image.id),
                str(path.resolve()),
                output.provider_name,
                output.model_name,
                output.model_version,
                self._learning_signature(snapshot.character_adjustments, snapshot.series_adjustments, snapshot.alias_adjustments, snapshot.accepted_corrections, snapshot.rejected_corrections, snapshot.review_items_scanned),
                ",".join(label.name for label in output.characters),
                ",".join(candidate.name for candidate in output.character_candidates),
            ]
        )

    @staticmethod
    def _learning_signature(
        character_adjustments: dict[int, float],
        series_adjustments: dict[int, float],
        alias_adjustments: dict[str, float],
        accepted: int,
        rejected: int,
        scanned: int,
    ) -> str:
        return "|".join(
            [
                f"c:{sorted(character_adjustments.items())}",
                f"s:{sorted(series_adjustments.items())}",
                f"a:{sorted(alias_adjustments.items())}",
                f"ok:{accepted}",
                f"no:{rejected}",
                f"scan:{scanned}",
            ]
        )

    def _clone(self, result: RecognitionMatchResult, *, cache_hit: bool) -> RecognitionMatchResult:
        return RecognitionMatchResult(
            assignment=RecognitionAssignment(
                character_id=result.assignment.character_id,
                series_id=result.assignment.series_id,
                character_name=result.assignment.character_name,
                series_name=result.assignment.series_name,
                confidence=result.assignment.confidence,
                auto_assigned=result.assignment.auto_assigned,
                needs_review=result.assignment.needs_review,
                reason=result.assignment.reason,
                candidates=[
                    RecognitionCandidate(
                        character_id=item.character_id,
                        series_id=item.series_id,
                        character_name=item.character_name,
                        series_name=item.series_name,
                        confidence=item.confidence,
                        normalized_label=item.normalized_label,
                        matched_alias=item.matched_alias,
                        source_labels=list(item.source_labels),
                        score_breakdown=dict(item.score_breakdown),
                        rank=item.rank,
                        unknown=item.unknown,
                    )
                    for item in result.assignment.candidates
                ],
                source_labels=[RecognitionLabel(name=item.name, confidence=item.confidence) for item in result.assignment.source_labels],
                metadata=dict(result.assignment.metadata),
                review_item_id=result.assignment.review_item_id,
            ),
            candidates=[
                RecognitionCandidate(
                    character_id=item.character_id,
                    series_id=item.series_id,
                    character_name=item.character_name,
                    series_name=item.series_name,
                    confidence=item.confidence,
                    normalized_label=item.normalized_label,
                    matched_alias=item.matched_alias,
                    source_labels=list(item.source_labels),
                    score_breakdown=dict(item.score_breakdown),
                    rank=item.rank,
                    unknown=item.unknown,
                )
                for item in result.candidates
            ],
            cache_hit=cache_hit,
            matching_time_seconds=result.matching_time_seconds,
            ranking_time_seconds=result.ranking_time_seconds,
            series_candidates=[
                SeriesRecord(
                    series_id=item.series_id,
                    canonical_title=item.canonical_title,
                    aliases=list(item.aliases),
                    japanese_title=item.japanese_title,
                    english_title=item.english_title,
                    romaji=item.romaji,
                    franchise=item.franchise,
                    parent_series_id=item.parent_series_id,
                    spin_off_ids=list(item.spin_off_ids),
                    sequel_ids=list(item.sequel_ids),
                    prequel_ids=list(item.prequel_ids),
                )
                for item in result.series_candidates
            ],
            metadata=dict(result.metadata),
            review_item_id=result.review_item_id,
        )
