from __future__ import annotations

import json
import zlib
from dataclasses import asdict
from datetime import datetime, timezone

from engine.adaptive_learning.adaptive_models import (
    AdaptiveCandidate,
    AdaptiveConfidenceResult,
    AdaptiveConfidenceWeights,
    AdaptiveEvidence,
    AdaptiveUncertaintyItem,
    CharacterLearningProfile,
)


class AdaptiveLearningBuilder:
    """Builder utilities for adaptive profile updates, confidence scoring, and compressed persistence."""

    def ensure_profile(
        self,
        *,
        profiles: dict[str, CharacterLearningProfile],
        canonical_character_id: str,
        canonical_series_id: str,
    ) -> CharacterLearningProfile:
        key = self.profile_key(canonical_character_id=canonical_character_id, canonical_series_id=canonical_series_id)
        profile = profiles.get(key)
        if profile is None:
            profile = CharacterLearningProfile(
                canonical_character_id=canonical_character_id,
                canonical_series_id=canonical_series_id,
            )
            profiles[key] = profile
        return profile

    def apply_evidence(self, *, profile: CharacterLearningProfile, evidence: AdaptiveEvidence) -> None:
        profile.confidence_history.append(float(evidence.confidence))
        profile.last_updated = datetime.now(timezone.utc)
        if evidence.accepted:
            profile.accepted_matches += 1
        if evidence.rejected:
            profile.rejected_matches += 1
        if evidence.false_positive:
            profile.false_positives += 1
        if evidence.false_negative:
            profile.false_negatives += 1

        if evidence.embedding_key and evidence.embedding_vector:
            profile.embedding_history[evidence.embedding_key] = list(evidence.embedding_vector)

        if evidence.visual_fingerprint:
            if evidence.visual_fingerprint not in profile.visual_fingerprint_history:
                profile.visual_fingerprint_history.append(evidence.visual_fingerprint)

        self._increment_optional(profile.filename_patterns, evidence.filename_pattern)
        self._increment_optional(profile.folder_patterns, evidence.folder_pattern)
        self._increment_many(profile.alias_usage, evidence.aliases)
        self._increment_optional(profile.pose_frequency, evidence.pose)
        self._increment_optional(profile.hairstyle_frequency, evidence.hairstyle)
        self._increment_optional(profile.clothing_frequency, evidence.clothing)
        self._increment_optional(profile.dominant_color_palette, evidence.dominant_palette)
        self._increment_many(profile.accessory_frequency, evidence.accessories)
        self._increment_many(profile.co_occurring_characters, evidence.co_occurring_characters)
        self._increment_many(profile.co_occurring_series, evidence.co_occurring_series)
        for relation in evidence.relationships:
            encoded = f"{relation[0]}->{relation[1]}"
            profile.relationship_graph[encoded] = profile.relationship_graph.get(encoded, 0) + 1

        profile.learning_score = self.compute_learning_score(profile)

    def compute_learning_score(self, profile: CharacterLearningProfile) -> float:
        positives = float(profile.accepted_matches)
        negatives = float(profile.rejected_matches + profile.false_positives + profile.false_negatives)
        total = positives + negatives
        if total <= 0.0:
            return 0.0
        confidence = sum(profile.confidence_history[-25:]) / float(max(1, len(profile.confidence_history[-25:])))
        base = (positives / total) * 0.7
        return round(max(0.0, min(1.0, base + (confidence * 0.3))), 6)

    def score_candidate(
        self,
        *,
        candidate: AdaptiveCandidate,
        weights: AdaptiveConfidenceWeights,
        profile: CharacterLearningProfile | None,
    ) -> AdaptiveConfidenceResult:
        normalized = weights.normalized()
        accepted = 0.0 if profile is None else float(profile.accepted_matches)
        rejected = 0.0 if profile is None else float(profile.rejected_matches)
        precision = 0.0 if profile is None else profile.learning_score
        review_history = 0.0
        if profile is not None:
            total_reviews = accepted + rejected
            review_history = 0.0 if total_reviews <= 0 else accepted / total_reviews

        feature_values = {
            "review_history": review_history,
            "previous_approvals": min(1.0, accepted / 100.0),
            "previous_rejections": min(1.0, rejected / 100.0),
            "knowledge_pack_confidence": candidate.features.get("knowledge_pack_confidence", 0.0),
            "embedding_similarity": candidate.features.get("embedding_similarity", 0.0),
            "filename_similarity": candidate.features.get("filename_similarity", 0.0),
            "folder_similarity": candidate.features.get("folder_similarity", 0.0),
            "relationship_graph": candidate.features.get("relationship_graph", 0.0),
            "series_probability": candidate.features.get("series_probability", 0.0),
            "user_correction_history": candidate.features.get("user_correction_history", review_history),
            "historical_precision": precision,
        }

        components: dict[str, float] = {}
        weighted_sum = 0.0
        for key, weight in normalized.items():
            value = max(0.0, min(1.0, float(feature_values.get(key, 0.0))))
            # Rejection terms reduce confidence while remaining a weighted contributor.
            if key == "previous_rejections":
                value = 1.0 - value
            contribution = value * weight
            components[key] = contribution
            weighted_sum += contribution

        score = max(0.0, min(1.0, (candidate.base_confidence * 0.5) + (weighted_sum * 0.5)))
        return AdaptiveConfidenceResult(
            canonical_character_id=candidate.canonical_character_id,
            canonical_series_id=candidate.canonical_series_id,
            score=round(score, 6),
            components=components,
        )

    def disambiguate_identical_names(
        self,
        *,
        candidates: list[AdaptiveConfidenceResult],
        series_hint: str | None,
    ) -> AdaptiveConfidenceResult | None:
        if not candidates:
            return None
        if series_hint:
            preferred = [item for item in candidates if item.canonical_series_id == series_hint]
            if preferred:
                return max(preferred, key=lambda item: item.score)
        return max(candidates, key=lambda item: item.score)

    def sort_uncertainty_queue(self, items: list[AdaptiveUncertaintyItem]) -> list[AdaptiveUncertaintyItem]:
        return sorted(items, key=lambda item: item.priority)

    def profile_key(self, *, canonical_character_id: str, canonical_series_id: str) -> str:
        return f"{canonical_character_id}::{canonical_series_id}"

    def serialize_state(self, *, profiles: dict[str, CharacterLearningProfile], uncertainty: list[AdaptiveUncertaintyItem]) -> bytes:
        payload = {
            "profiles": {key: asdict(value) for key, value in profiles.items()},
            "uncertainty": [asdict(item) for item in uncertainty],
        }
        return zlib.compress(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))

    def deserialize_state(self, payload: bytes) -> tuple[dict[str, CharacterLearningProfile], list[AdaptiveUncertaintyItem]]:
        raw = zlib.decompress(payload)
        data = json.loads(raw.decode("utf-8"))
        profiles: dict[str, CharacterLearningProfile] = {}
        for key, value in dict(data.get("profiles", {})).items():
            updated = value.get("last_updated")
            if isinstance(updated, str):
                try:
                    value["last_updated"] = datetime.fromisoformat(updated)
                except ValueError:
                    value["last_updated"] = datetime.now(timezone.utc)
            profile = CharacterLearningProfile(**value)
            profiles[key] = profile
        uncertainty = [AdaptiveUncertaintyItem(**item) for item in list(data.get("uncertainty", []))]
        return profiles, uncertainty

    def _increment_optional(self, target: dict[str, int], value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip()
        if not normalized:
            return
        target[normalized] = target.get(normalized, 0) + 1

    def _increment_many(self, target: dict[str, int], values: list[str]) -> None:
        for value in values:
            self._increment_optional(target, value)
