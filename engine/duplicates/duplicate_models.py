from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MatchType(str, Enum):
    """Classification of a detected duplicate relationship."""

    EXACT = "exact"
    PERCEPTUAL = "perceptual"


class ConfidenceLevel(str, Enum):
    """Confidence tier for a detected duplicate pair."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(slots=True)
class SimilarityWeights:
    """Configurable weights for the perceptual hash similarity score.

    Weights must sum to 1.0.  The defaults place the most emphasis on pHash
    because it captures global image structure via the DCT.
    """

    phash: float = 0.5
    ahash: float = 0.25
    dhash: float = 0.25

    def __post_init__(self) -> None:
        total = self.phash + self.ahash + self.dhash
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"SimilarityWeights must sum to 1.0, got {total:.6f}"
            )


@dataclass(slots=True)
class SimilarityThresholds:
    """Configurable Hamming-distance thresholds for each confidence tier.

    Values represent the **maximum** allowable normalised Hamming distance
    (0.0 = identical, 1.0 = completely different).  A weighted score that
    falls below ``low`` is rejected outright.
    """

    high: float = 0.10
    """Weighted distance ≤ this → HIGH confidence."""

    medium: float = 0.20
    """Weighted distance ≤ this → MEDIUM confidence."""

    low: float = 0.35
    """Weighted distance ≤ this → LOW confidence; above this is rejected."""

    def __post_init__(self) -> None:
        if not (0.0 <= self.high <= self.medium <= self.low <= 1.0):
            raise ValueError(
                "Thresholds must satisfy 0 ≤ high ≤ medium ≤ low ≤ 1"
            )


@dataclass(slots=True)
class HashDistances:
    """Raw Hamming distances between the individual perceptual hashes of two images."""

    phash: int | None = None
    ahash: int | None = None
    dhash: int | None = None


@dataclass(slots=True)
class DuplicatePair:
    """A confirmed duplicate relationship between two images.

    ``image_a_id`` is always the lower integer so that the pair representation
    is canonical and can be used as a set key without ordering ambiguity.
    """

    image_a_id: int
    image_b_id: int
    source_path_a: str
    source_path_b: str
    match_type: MatchType
    confidence: ConfidenceLevel
    distances: HashDistances
    overall_score: float
    sha256_match: bool = False
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_key(self) -> frozenset[int]:
        """Return a frozenset of the two image ids for use as a checkpoint key."""
        return frozenset({self.image_a_id, self.image_b_id})


@dataclass(slots=True)
class DuplicateCheckpoint:
    """Minimal crash-recovery state for an interrupted duplicate scan.

    ``compared_pairs`` is a set of frozen two-element sets of image ids that
    were already compared.  On restart the engine skips any pair whose
    canonical key is already in this set.
    """

    compared_pairs: set[frozenset[int]] = field(default_factory=set)
    completed: bool = False
