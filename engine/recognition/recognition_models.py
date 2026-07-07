from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass(slots=True)
class RecognitionLabel:
    """A single recognized label and confidence score."""

    name: str
    confidence: float


@dataclass(slots=True)
class CharacterCandidate:
    """Ranked candidate for character recognition."""

    name: str
    confidence: float
    occurrences: int = 1
    rank: int = 0


@dataclass(slots=True)
class RecognitionCandidate:
    """Canonical candidate resolved from the character knowledge database."""

    character_id: int | None
    series_id: int | None
    character_name: str
    series_name: str | None
    confidence: float
    normalized_label: str = ""
    matched_alias: str = ""
    source_labels: list[str] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)
    rank: int = 0
    unknown: bool = False


@dataclass(slots=True)
class RecognitionContext:
    """Resolved input context used by the intelligent recognition pipeline."""

    image_id: int
    path: Path
    filename: str
    folder_name: str
    folder_parts: list[str] = field(default_factory=list)
    current_series_id: int | None = None
    current_series_name: str | None = None
    current_character_names: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    review_history: list[dict[str, Any]] = field(default_factory=list)
    ai_series_name: str | None = None
    ai_character_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RecognitionAssignment:
    """Final recognition decision for an image."""

    character_id: int | None
    series_id: int | None
    character_name: str | None
    series_name: str | None
    confidence: float
    auto_assigned: bool
    needs_review: bool
    reason: str = ""
    candidates: list[RecognitionCandidate] = field(default_factory=list)
    source_labels: list[RecognitionLabel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    review_item_id: int | None = None


def rank_character_candidates(
    labels: list[RecognitionLabel],
    *,
    limit: int | None = None,
) -> list[CharacterCandidate]:
    """Deduplicate, score, and rank character candidates."""
    merged: dict[str, tuple[float, int]] = {}
    for label in labels:
        name = label.name.strip()
        if not name:
            continue
        best_confidence, count = merged.get(name, (0.0, 0))
        merged[name] = (max(best_confidence, label.confidence), count + 1)

    ranked: list[CharacterCandidate] = []
    for name, (confidence, occurrences) in merged.items():
        # Repeated detections are rewarded with a small confidence bonus.
        bonus = min(0.005 * max(0, occurrences - 1), 0.02)
        ranked.append(
            CharacterCandidate(
                name=name,
                confidence=min(0.9999, round(confidence + bonus, 4)),
                occurrences=occurrences,
            )
        )

    ranked.sort(key=lambda item: (-item.confidence, -item.occurrences, item.name))
    if limit is not None:
        ranked = ranked[:limit]

    for index, item in enumerate(ranked, start=1):
        item.rank = index
    return ranked


@dataclass(slots=True)
class RecognitionOutput:
    """Recognition output for one image."""

    series: RecognitionLabel | None = None
    characters: list[RecognitionLabel] = field(default_factory=list)
    character_candidates: list[CharacterCandidate] = field(default_factory=list)
    overall_confidence: float | None = None
    provider_name: str = "unknown"
    model_name: str = "unknown"
    model_version: str = "1.0.0"
    assigned_character_id: int | None = None
    assigned_series_id: int | None = None
    assignment_confidence: float | None = None
    requires_review: bool = False
    candidate_payloads: list[RecognitionCandidate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.character_candidates and self.characters:
            self.character_candidates = rank_character_candidates(self.characters)
        elif self.character_candidates:
            self.character_candidates.sort(key=lambda item: item.rank if item.rank > 0 else 10**9)
            for index, item in enumerate(self.character_candidates, start=1):
                item.rank = index

        if not self.characters and self.character_candidates:
            self.characters = [
                RecognitionLabel(name=item.name, confidence=item.confidence)
                for item in self.character_candidates
            ]

        if self.overall_confidence is None:
            self.overall_confidence = self.confidence_score()

        if self.assignment_confidence is None:
            self.assignment_confidence = self.overall_confidence

    def confidence_score(self) -> float | None:
        """Compute an aggregate confidence across series and candidates."""
        components: list[float] = []
        if self.series is not None:
            components.append(self.series.confidence)

        top_candidates = self.character_candidates[:3]
        components.extend(candidate.confidence for candidate in top_candidates)
        if not components:
            return None
        return round(sum(components) / len(components), 4)

    def ranked_character_names(self) -> list[str]:
        """Return ranked character names in descending confidence order."""
        if self.character_candidates:
            return [candidate.name for candidate in self.character_candidates]
        return [label.name for label in self.characters]


@dataclass(slots=True)
class RecognitionAggregation:
    """Summary of a recognition run across multiple images."""

    total_results: int = 0
    recognized_series_count: int = 0
    recognized_character_count: int = 0
    average_series_confidence: float | None = None
    average_character_confidence: float | None = None
    average_overall_confidence: float | None = None
    top_series: list[tuple[str, int]] = field(default_factory=list)
    top_characters: list[tuple[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class RecognitionResult:
    """Persisted recognition result for one image path."""

    image_id: int
    path: Path
    output: RecognitionOutput
    assignment: RecognitionAssignment | None = None
    review_item_id: int | None = None
    auto_assigned: bool = False
    needs_review: bool = False
    matched_candidates: list[RecognitionCandidate] = field(default_factory=list)
    recognized_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def aggregate_recognition_results(
    results: list[RecognitionResult],
    *,
    top_n: int = 10,
) -> RecognitionAggregation:
    """Aggregate recognition results into summary statistics."""
    if not results:
        return RecognitionAggregation()

    series_counter: Counter[str] = Counter()
    character_counter: Counter[str] = Counter()
    series_confidences: list[float] = []
    character_confidences: list[float] = []
    overall_confidences: list[float] = []

    for result in results:
        output = result.output
        if output.series is not None:
            series_counter[output.series.name] += 1
            series_confidences.append(output.series.confidence)

        candidates = output.character_candidates or rank_character_candidates(output.characters)
        for candidate in candidates:
            character_counter[candidate.name] += 1
            character_confidences.append(candidate.confidence)

        score = output.overall_confidence if output.overall_confidence is not None else output.confidence_score()
        if score is not None:
            overall_confidences.append(score)

    return RecognitionAggregation(
        total_results=len(results),
        recognized_series_count=sum(series_counter.values()),
        recognized_character_count=sum(character_counter.values()),
        average_series_confidence=round(sum(series_confidences) / len(series_confidences), 4)
        if series_confidences
        else None,
        average_character_confidence=round(sum(character_confidences) / len(character_confidences), 4)
        if character_confidences
        else None,
        average_overall_confidence=round(sum(overall_confidences) / len(overall_confidences), 4)
        if overall_confidences
        else None,
        top_series=series_counter.most_common(top_n),
        top_characters=character_counter.most_common(top_n),
    )


class RecognitionCache:
    """Thread-safe in-memory cache for recognition outputs."""

    def __init__(self, max_size: int = 5000) -> None:
        self.max_size = max_size
        self._cache: dict[str, RecognitionOutput] = {}
        self._lock = Lock()

    def get(self, cache_key: str) -> RecognitionOutput | None:
        with self._lock:
            output = self._cache.get(cache_key)
        if output is None:
            return None
        return self._clone_output(output)

    def put(self, cache_key: str, output: RecognitionOutput) -> None:
        cloned = self._clone_output(output)
        with self._lock:
            if len(self._cache) >= self.max_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = cloned

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @staticmethod
    def _clone_output(output: RecognitionOutput) -> RecognitionOutput:
        return RecognitionOutput(
            series=(
                RecognitionLabel(name=output.series.name, confidence=output.series.confidence)
                if output.series is not None
                else None
            ),
            characters=[RecognitionLabel(name=item.name, confidence=item.confidence) for item in output.characters],
            character_candidates=[
                CharacterCandidate(
                    name=item.name,
                    confidence=item.confidence,
                    occurrences=item.occurrences,
                    rank=item.rank,
                )
                for item in output.character_candidates
            ],
            overall_confidence=output.overall_confidence,
            provider_name=output.provider_name,
            model_name=output.model_name,
            model_version=output.model_version,
        )


@dataclass(slots=True)
class RecognitionCheckpoint:
    """Crash recovery checkpoint for recognition runs."""

    processed_paths: set[str] = field(default_factory=set)

    def add_processed(self, path: str | Path) -> None:
        """Mark a path as processed."""
        self.processed_paths.add(str(path))

    def is_processed(self, path: str | Path) -> bool:
        """Return True when *path* is already processed."""
        return str(path) in self.processed_paths
