from engine.duplicates.duplicate_engine import DuplicateEngine
from engine.duplicates.duplicate_events import (
    DuplicateCompleted,
    DuplicateFound,
    DuplicateRejected,
    DuplicateStarted,
)
from engine.duplicates.duplicate_exceptions import (
    DuplicateComparisonError,
    DuplicateEngineError,
    DuplicatePersistenceError,
    InvalidHashError,
)
from engine.duplicates.duplicate_matcher import DuplicateMatcher, hamming_distance, normalized_hamming
from engine.duplicates.duplicate_models import (
    ConfidenceLevel,
    DuplicateCheckpoint,
    DuplicatePair,
    HashDistances,
    MatchType,
    SimilarityThresholds,
    SimilarityWeights,
)
from engine.duplicates.duplicate_service import DuplicateService
from engine.duplicates.duplicate_statistics import DuplicateStatistics
from engine.duplicates.duplicate_worker import DuplicateWorker

__all__ = [
    "ConfidenceLevel",
    "DuplicateCheckpoint",
    "DuplicateComparisonError",
    "DuplicateCompleted",
    "DuplicateEngine",
    "DuplicateEngineError",
    "DuplicateFound",
    "DuplicateMatcher",
    "DuplicatePair",
    "DuplicatePersistenceError",
    "DuplicateRejected",
    "DuplicateService",
    "DuplicateStarted",
    "DuplicateStatistics",
    "DuplicateWorker",
    "HashDistances",
    "InvalidHashError",
    "MatchType",
    "SimilarityThresholds",
    "SimilarityWeights",
    "hamming_distance",
    "normalized_hamming",
]
