from __future__ import annotations

from engine.duplicates.duplicate_exceptions import InvalidHashError
from engine.duplicates.duplicate_models import (
    ConfidenceLevel,
    DuplicatePair,
    HashDistances,
    MatchType,
    SimilarityThresholds,
    SimilarityWeights,
)
from engine.hashing.hash_models import DuplicateCandidate

# Number of bits in a standard 64-bit perceptual hash (16 hex digits).
_HASH_BITS: int = 64


def hamming_distance(a: str, b: str) -> int:
    """Return the Hamming distance between two equal-length hex hash strings.

    Both strings must represent the same number of bits.  The comparison is
    performed via integer XOR so no bit-by-bit iteration is required.

    Raises
    ------
    InvalidHashError
        If either string is not a valid hexadecimal value or if the strings
        have different lengths.
    """
    if len(a) != len(b):
        raise InvalidHashError(
            f"Hash length mismatch: {len(a)} != {len(b)} ('{a}' vs '{b}')"
        )
    try:
        xor = int(a, 16) ^ int(b, 16)
    except ValueError as exc:
        raise InvalidHashError(f"Invalid hex hash value: {exc}") from exc
    return bin(xor).count("1")


def normalized_hamming(a: str, b: str, bits: int = _HASH_BITS) -> float:
    """Return Hamming distance normalised to [0, 1].

    0.0 means identical; 1.0 means every bit differs.
    """
    return hamming_distance(a, b) / bits


class DuplicateMatcher:
    """Perceptual and exact-match duplicate detector.

    Design
    ------
    The matcher maintains an in-memory list of previously seen
    :class:`~engine.hashing.hash_models.DuplicateCandidate` objects.
    When a new candidate is submitted via :meth:`find_matches`, it is
    compared against every registered candidate using the configured weights
    and thresholds.

    This linear-scan strategy is correct and simple.  The interface is
    deliberately shaped so that a BK-tree or VP-tree index can replace the
    ``_candidates`` list and the inner loop in :meth:`_compare_perceptual`
    without changing the public API.

    Parameters
    ----------
    weights:
        Per-hash weights for the similarity score.  Must sum to 1.0.
    thresholds:
        Maximum normalised Hamming distance for each confidence tier.
    """

    def __init__(
        self,
        weights: SimilarityWeights | None = None,
        thresholds: SimilarityThresholds | None = None,
    ) -> None:
        self.weights: SimilarityWeights = weights or SimilarityWeights()
        self.thresholds: SimilarityThresholds = thresholds or SimilarityThresholds()
        self._candidates: list[DuplicateCandidate] = []
        # Index for O(1) exact-duplicate lookup: sha256 → list of candidates
        self._sha256_index: dict[str, list[DuplicateCandidate]] = {}

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def add_candidate(self, candidate: DuplicateCandidate) -> None:
        """Register *candidate* for future comparisons.

        Must be called for every previously indexed image before calling
        :meth:`find_matches` so that the matcher has a complete view of the
        existing image set.
        """
        self._candidates.append(candidate)
        if candidate.sha256:
            self._sha256_index.setdefault(candidate.sha256, []).append(candidate)

    def candidate_count(self) -> int:
        """Return the number of registered candidates."""
        return len(self._candidates)

    # ------------------------------------------------------------------ #
    # Matching                                                             #
    # ------------------------------------------------------------------ #

    def find_matches(
        self,
        target: DuplicateCandidate,
        *,
        already_compared: set[frozenset[int]] | None = None,
    ) -> list[DuplicatePair]:
        """Return all duplicate pairs where *target* is one member.

        Parameters
        ----------
        target:
            The new candidate to compare against all registered candidates.
        already_compared:
            Optional set of canonical pair keys (frozensets of two image ids)
            that have already been compared and must be skipped.  Used for
            crash recovery.
        """
        already_compared = already_compared or set()
        pairs: list[DuplicatePair] = []

        for candidate in self._candidates:
            if candidate.image_id == target.image_id:
                continue
            key = frozenset({candidate.image_id, target.image_id})
            if key in already_compared:
                continue

            pair = self._compare(target, candidate)
            if pair is not None:
                pairs.append(pair)

        return pairs

    # ------------------------------------------------------------------ #
    # Internal comparison logic                                            #
    # ------------------------------------------------------------------ #

    def _compare(
        self, a: DuplicateCandidate, b: DuplicateCandidate
    ) -> DuplicatePair | None:
        """Compare *a* and *b*; return a :class:`DuplicatePair` or ``None``."""
        # Canonical ordering: lower image_id is always "a"
        if a.image_id > b.image_id:
            a, b = b, a

        # --- Exact match via SHA-256 ---
        if a.sha256 and b.sha256 and a.sha256 == b.sha256:
            return DuplicatePair(
                image_a_id=a.image_id,
                image_b_id=b.image_id,
                source_path_a=a.source_path,
                source_path_b=b.source_path,
                match_type=MatchType.EXACT,
                confidence=ConfidenceLevel.HIGH,
                distances=HashDistances(),
                overall_score=1.0,
                sha256_match=True,
            )

        # --- Perceptual match via weighted Hamming distance ---
        return self._compare_perceptual(a, b)

    def _compare_perceptual(
        self, a: DuplicateCandidate, b: DuplicateCandidate
    ) -> DuplicatePair | None:
        """Compute a weighted similarity score and return a pair if above threshold."""
        distances = HashDistances(
            phash=self._safe_hamming(a.phash, b.phash),
            ahash=self._safe_hamming(a.ahash, b.ahash),
            dhash=self._safe_hamming(a.dhash, b.dhash),
        )

        # Compute weighted normalised distance only for available hashes
        total_weight: float = 0.0
        weighted_distance: float = 0.0

        if distances.phash is not None:
            norm = distances.phash / _HASH_BITS
            weighted_distance += self.weights.phash * norm
            total_weight += self.weights.phash

        if distances.ahash is not None:
            norm = distances.ahash / _HASH_BITS
            weighted_distance += self.weights.ahash * norm
            total_weight += self.weights.ahash

        if distances.dhash is not None:
            norm = distances.dhash / _HASH_BITS
            weighted_distance += self.weights.dhash * norm
            total_weight += self.weights.dhash

        if total_weight == 0.0:
            # No perceptual hashes available for either image
            return None

        # Normalise by the total weight so the score is still in [0, 1]
        effective_distance = weighted_distance / total_weight
        overall_score = 1.0 - effective_distance

        confidence = self._classify_confidence(effective_distance)
        if confidence is None:
            return None

        return DuplicatePair(
            image_a_id=a.image_id,
            image_b_id=b.image_id,
            source_path_a=a.source_path,
            source_path_b=b.source_path,
            match_type=MatchType.PERCEPTUAL,
            confidence=confidence,
            distances=distances,
            overall_score=round(overall_score, 6),
            sha256_match=False,
        )

    def _classify_confidence(
        self, normalised_distance: float
    ) -> ConfidenceLevel | None:
        """Map a normalised distance to a confidence tier or ``None`` if rejected."""
        if normalised_distance <= self.thresholds.high:
            return ConfidenceLevel.HIGH
        if normalised_distance <= self.thresholds.medium:
            return ConfidenceLevel.MEDIUM
        if normalised_distance <= self.thresholds.low:
            return ConfidenceLevel.LOW
        return None

    @staticmethod
    def _safe_hamming(a: str | None, b: str | None) -> int | None:
        """Compute Hamming distance or return ``None`` when either hash is absent."""
        if a is None or b is None:
            return None
        try:
            return hamming_distance(a, b)
        except InvalidHashError:
            return None
