from __future__ import annotations

from dataclasses import asdict
from time import perf_counter

from engine.adaptive_learning.adaptive_builder import AdaptiveLearningBuilder
from engine.adaptive_learning.adaptive_exceptions import AdaptiveProfileNotFoundError
from engine.adaptive_learning.adaptive_models import (
    AdaptiveCandidate,
    AdaptiveConfidenceResult,
    AdaptiveConfidenceWeights,
    AdaptiveEvidence,
    AdaptiveLearningResult,
    AdaptiveUncertaintyItem,
    CharacterLearningProfile,
)
from engine.adaptive_learning.adaptive_statistics import AdaptiveLearningStatistics
from engine.repositories.adaptive_learning_repository import AdaptiveLearningRepository


class AdaptiveLearningEngine:
    """Self-improving adaptive learning engine driven by user corrections and knowledge sources."""

    def __init__(
        self,
        *,
        repository: AdaptiveLearningRepository | None = None,
        builder: AdaptiveLearningBuilder | None = None,
        weights: AdaptiveConfidenceWeights | None = None,
        callback=None,
    ) -> None:
        self.repository = repository or AdaptiveLearningRepository()
        self.builder = builder or AdaptiveLearningBuilder()
        self.weights = weights or AdaptiveConfidenceWeights()
        self.callback = callback
        self.statistics = AdaptiveLearningStatistics()
        self._adaptive_cache: dict[str, dict] = {}
        self._learning_cache: dict[str, float] = {}
        self._embedding_cache: dict[str, list[float]] = {}
        self._confidence_cache: dict[str, AdaptiveConfidenceResult] = {}

    def ingest_evidence(self, evidence: AdaptiveEvidence) -> AdaptiveLearningResult:
        started = perf_counter()
        self.repository.save_snapshot()
        profiles = self.repository.list_profiles()
        profile = self.builder.ensure_profile(
            profiles=profiles,
            canonical_character_id=evidence.canonical_character_id,
            canonical_series_id=evidence.canonical_series_id,
        )
        self.builder.apply_evidence(profile=profile, evidence=evidence)
        key = self.builder.profile_key(
            canonical_character_id=evidence.canonical_character_id,
            canonical_series_id=evidence.canonical_series_id,
        )
        self.repository.save_profile(key, profile)

        if evidence.embedding_key and evidence.embedding_vector and evidence.embedding_key not in self._embedding_cache:
            self._embedding_cache[evidence.embedding_key] = list(evidence.embedding_vector)

        uncertainty = self.repository.list_uncertainty_queue()
        uncertainty.append(
            AdaptiveUncertaintyItem(
                evidence_id=f"{evidence.canonical_character_id}:{len(profile.confidence_history)}",
                canonical_character_id=evidence.canonical_character_id,
                canonical_series_id=evidence.canonical_series_id,
                confidence=max(0.0, min(1.0, evidence.confidence)),
                ambiguity=max(0.0, min(1.0, evidence.ambiguity)),
                rare_character=bool(evidence.rare_character),
                unseen_alias=bool(evidence.unseen_alias),
            )
        )
        self.repository.set_uncertainty_queue(self.builder.sort_uncertainty_queue(uncertainty))

        self.statistics.learning_iterations += 1
        if evidence.accepted:
            self.statistics.accepted_samples += 1
        if evidence.rejected:
            self.statistics.rejected_samples += 1
        self._recompute_quality_metrics()
        self._invalidate_caches()
        self.repository.persist()
        self.statistics.training_duration_seconds += perf_counter() - started
        self._update_counters()
        return AdaptiveLearningResult(action="ingest_evidence", success=True)

    def incremental_train(self, evidence_items: list[AdaptiveEvidence]) -> AdaptiveLearningResult:
        for evidence in evidence_items:
            self.ingest_evidence(evidence)
        return AdaptiveLearningResult(
            action="incremental_train",
            success=True,
            details={"processed": len(evidence_items)},
        )

    def rollback(self) -> AdaptiveLearningResult:
        restored = self.repository.rollback()
        if restored:
            self._invalidate_caches()
            self._update_counters()
            return AdaptiveLearningResult(action="rollback", success=True)
        return AdaptiveLearningResult(action="rollback", success=False, message="No snapshots available")

    def profile_for(self, *, canonical_character_id: str, canonical_series_id: str) -> CharacterLearningProfile:
        key = self.builder.profile_key(
            canonical_character_id=canonical_character_id,
            canonical_series_id=canonical_series_id,
        )
        profile = self.repository.list_profiles().get(key)
        if profile is None:
            raise AdaptiveProfileNotFoundError(f"Profile not found for {key}")
        return profile

    def score_candidates(
        self,
        *,
        candidates: list[AdaptiveCandidate],
        series_hint: str | None = None,
        weights: AdaptiveConfidenceWeights | None = None,
    ) -> tuple[list[AdaptiveConfidenceResult], AdaptiveConfidenceResult | None]:
        active_weights = weights or self.weights
        profiles = self.repository.list_profiles()
        results: list[AdaptiveConfidenceResult] = []
        for candidate in candidates:
            cache_key = f"{candidate.canonical_character_id}:{candidate.canonical_series_id}:{hash(tuple(sorted(candidate.features.items())))}"
            cached = self._confidence_cache.get(cache_key)
            if cached is not None:
                self.statistics.cache_hits += 1
                results.append(cached)
                continue
            self.statistics.cache_misses += 1
            profile_key = self.builder.profile_key(
                canonical_character_id=candidate.canonical_character_id,
                canonical_series_id=candidate.canonical_series_id,
            )
            scored = self.builder.score_candidate(
                candidate=candidate,
                weights=active_weights,
                profile=profiles.get(profile_key),
            )
            self._confidence_cache[cache_key] = scored
            results.append(scored)
        best = self.builder.disambiguate_identical_names(candidates=results, series_hint=series_hint)
        return results, best

    def active_learning_queue(self, *, limit: int = 50) -> list[AdaptiveUncertaintyItem]:
        queue = self.repository.list_uncertainty_queue()
        ordered = self.builder.sort_uncertainty_queue(queue)
        self.statistics.uncertainty_queue_size = len(ordered)
        return ordered[: max(1, limit)]

    def persist(self) -> bytes:
        payload = self.repository.persist()
        self._update_counters()
        return payload

    def load(self, payload: bytes | None = None) -> AdaptiveLearningResult:
        self.repository.load(payload)
        self._invalidate_caches()
        self._update_counters()
        return AdaptiveLearningResult(action="load", success=True)

    def recover_from_corruption(self) -> AdaptiveLearningResult:
        self.repository.recover_from_corruption()
        self._invalidate_caches()
        self._update_counters()
        return AdaptiveLearningResult(action="recover", success=True)

    def snapshot_statistics(self) -> AdaptiveLearningStatistics:
        self._update_counters()
        return AdaptiveLearningStatistics(**asdict(self.statistics))

    def _recompute_quality_metrics(self) -> None:
        accepted = float(self.statistics.accepted_samples)
        rejected = float(self.statistics.rejected_samples)
        total = accepted + rejected
        if total <= 0.0:
            self.statistics.precision_improvement = 0.0
            self.statistics.recall_improvement = 0.0
            self.statistics.confidence_evolution = 0.0
            return
        precision = accepted / total
        recall = accepted / max(1.0, accepted + (rejected * 0.5))
        self.statistics.precision_improvement = round(max(0.0, precision - 0.5), 6)
        self.statistics.recall_improvement = round(max(0.0, recall - 0.5), 6)

        profiles = self.repository.list_profiles().values()
        scores = [item.learning_score for item in profiles]
        self.statistics.confidence_evolution = round(sum(scores) / float(max(1, len(scores))), 6)

    def _invalidate_caches(self) -> None:
        self._adaptive_cache.clear()
        self._learning_cache.clear()
        self._confidence_cache.clear()

    def _update_counters(self) -> None:
        self.statistics.active_profiles = len(self.repository.list_profiles())
        self.statistics.uncertainty_queue_size = len(self.repository.list_uncertainty_queue())
