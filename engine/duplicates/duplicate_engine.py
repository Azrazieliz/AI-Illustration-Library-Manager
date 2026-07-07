from __future__ import annotations

from typing import Callable, Iterable

from engine.duplicates.duplicate_events import (
    DuplicateCompleted,
    DuplicateFound,
    DuplicateRejected,
    DuplicateStarted,
)
from engine.duplicates.duplicate_exceptions import DuplicatePersistenceError
from engine.duplicates.duplicate_matcher import DuplicateMatcher
from engine.duplicates.duplicate_models import (
    DuplicateCheckpoint,
    DuplicatePair,
    MatchType,
    SimilarityThresholds,
    SimilarityWeights,
)
from engine.duplicates.duplicate_statistics import DuplicateStatistics
from engine.hashing.hash_models import DuplicateCandidate
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.hash_repository import HashRepository
from engine.repositories.image_repository import ImageRepository


class DuplicateEngine:
    """Consumes :class:`~engine.hashing.hash_models.DuplicateCandidate` objects,
    compares them against the entire known image set, and persists confirmed
    duplicate relationships through the repository layer.

    Crash Recovery
    --------------
    The engine accepts a :class:`DuplicateCheckpoint` containing the set of
    pair keys that have already been compared.  On restart, those pairs are
    skipped so no comparison is ever performed twice.

    Performance
    -----------
    Exact duplicates are detected in O(1) via the SHA-256 index in
    :class:`DuplicateMatcher`.  Perceptual comparisons use a linear scan
    against registered candidates.  The matcher interface is shaped to allow
    BK-tree / VP-tree replacement without touching the engine.
    """

    def __init__(
        self,
        *,
        image_repository: ImageRepository | None = None,
        hash_repository: HashRepository | None = None,
        duplicate_repository: DuplicateRepository | None = None,
        weights: SimilarityWeights | None = None,
        thresholds: SimilarityThresholds | None = None,
        callback: Callable[[object], None] | None = None,
    ) -> None:
        self.image_repository = image_repository or ImageRepository()
        self.hash_repository = hash_repository or HashRepository()
        self.duplicate_repository = duplicate_repository or DuplicateRepository()
        self.callback = callback
        self.statistics = DuplicateStatistics()
        self._matcher = DuplicateMatcher(weights=weights, thresholds=thresholds)
        self._loaded = False

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def process_candidates(
        self,
        candidates: Iterable[DuplicateCandidate],
        *,
        checkpoint: DuplicateCheckpoint | None = None,
    ) -> list[DuplicatePair]:
        """Process *candidates* and return all confirmed duplicate pairs.

        The engine loads the full existing image-hash state on the first call
        so it can compare each incoming candidate against all previously
        indexed images.
        """
        self.statistics = DuplicateStatistics()
        self.statistics.start()
        self._ensure_loaded()
        pairs: list[DuplicatePair] = []
        already_compared: set[frozenset[int]] = (
            set(checkpoint.compared_pairs) if checkpoint else set()
        )

        for candidate in candidates:
            self._emit(DuplicateStarted(source_path=candidate.source_path))
            try:
                new_pairs = self._process_one(candidate, already_compared)
                pairs.extend(new_pairs)
                # Register the candidate for subsequent comparisons in this batch
                self._matcher.add_candidate(candidate)
                # Update checkpoint so restarts skip already-compared pairs
                if checkpoint is not None:
                    for pair in new_pairs:
                        checkpoint.compared_pairs.add(pair.canonical_key())
            except Exception as exc:
                self.statistics.failed += 1
                self._emit(
                    DuplicateRejected(
                        source_path_a=candidate.source_path,
                        source_path_b="",
                        reason=str(exc),
                    )
                )
            finally:
                self.statistics.processed += 1

        self.statistics.complete()
        self._emit(
            DuplicateCompleted(
                total_processed=self.statistics.processed,
                total_found=self.statistics.duplicates_found,
                total_rejected=self.statistics.false_matches_rejected,
            )
        )
        return pairs

    def process_candidate(
        self,
        candidate: DuplicateCandidate,
        *,
        checkpoint: DuplicateCheckpoint | None = None,
    ) -> list[DuplicatePair]:
        """Convenience wrapper to process a single candidate."""
        return self.process_candidates([candidate], checkpoint=checkpoint)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _ensure_loaded(self) -> None:
        """Populate the matcher with all existing hash records from the DB."""
        if self._loaded:
            return
        for hash_rec in self.hash_repository.list_all_hashes():
            image = self.image_repository.get_image(hash_rec.image_id)
            if image is None or not image.original_path:
                continue
            candidate = DuplicateCandidate(
                source_path=image.original_path,
                image_id=image.id,
                sha256=hash_rec.sha256,
                phash=hash_rec.phash,
                ahash=hash_rec.ahash,
                dhash=hash_rec.dhash,
            )
            self._matcher.add_candidate(candidate)
        self._loaded = True

    def _process_one(
        self,
        candidate: DuplicateCandidate,
        already_compared: set[frozenset[int]],
    ) -> list[DuplicatePair]:
        found: list[DuplicatePair] = []
        matches = self._matcher.find_matches(
            candidate, already_compared=already_compared
        )
        self.statistics.comparisons += self._matcher.candidate_count()

        for pair in matches:
            already_compared.add(pair.canonical_key())
            # Skip if already stored (idempotent on crash recovery)
            existing = self.duplicate_repository.get_canonical(
                pair.image_a_id, pair.image_b_id
            )
            if existing is not None:
                continue
            self._persist(pair)
            self._update_statistics(pair)
            self._emit(DuplicateFound(pair=pair))
            found.append(pair)

        rejected_count = self._matcher.candidate_count() - len(matches)
        # Subtract any pairs skipped via already_compared
        self.statistics.false_matches_rejected += max(0, rejected_count)

        return found

    def _persist(self, pair: DuplicatePair) -> None:
        try:
            self.duplicate_repository.create_duplicate(
                image_a_id=pair.image_a_id,
                image_b_id=pair.image_b_id,
                match_type=pair.match_type.value,
                confidence=pair.confidence.value,
                sha256_match=pair.sha256_match,
                phash_distance=pair.distances.phash,
                ahash_distance=pair.distances.ahash,
                dhash_distance=pair.distances.dhash,
                overall_score=pair.overall_score,
            )
        except Exception as exc:
            raise DuplicatePersistenceError(
                f"Failed to persist duplicate pair "
                f"({pair.image_a_id}, {pair.image_b_id})"
            ) from exc

    def _update_statistics(self, pair: DuplicatePair) -> None:
        self.statistics.duplicates_found += 1
        if pair.match_type is MatchType.EXACT:
            self.statistics.exact_duplicates += 1
        else:
            self.statistics.perceptual_duplicates += 1

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
