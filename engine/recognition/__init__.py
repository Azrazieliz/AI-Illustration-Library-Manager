from __future__ import annotations

from importlib import import_module

from engine.recognition.recognition_events import (
    RecognitionCompleted,
    RecognitionCompletedForPath,
    RecognitionFailed,
    RecognitionSkipped,
    RecognitionStarted,
)
from engine.recognition.recognition_exceptions import (
    RecognitionException,
    RecognitionPersistenceError,
    RecognitionProviderError,
    UnsupportedRecognitionProviderError,
)
from engine.recognition.recognition_models import (
    CharacterCandidate,
    RecognitionAggregation,
    RecognitionAssignment,
    RecognitionCache,
    RecognitionCandidate,
    RecognitionCheckpoint,
    RecognitionContext,
    RecognitionLabel,
    RecognitionOutput,
    RecognitionResult,
    aggregate_recognition_results,
    rank_character_candidates,
)
from engine.recognition.recognition_provider import (
    MockRecognitionProvider,
    RecognitionProvider,
    get_provider,
)
from engine.recognition.recognition_statistics import RecognitionStatistics

__all__ = [
    "CharacterCandidate",
    "MockRecognitionProvider",
    "RecognitionAggregation",
    "RecognitionAssignment",
    "RecognitionCache",
    "RecognitionCandidate",
    "RecognitionCheckpoint",
    "RecognitionCompleted",
    "RecognitionCompletedForPath",
    "RecognitionContext",
    "RecognitionEngine",
    "RecognitionException",
    "RecognitionFailed",
    "RecognitionLabel",
    "RecognitionOutput",
    "RecognitionPersistenceError",
    "RecognitionProvider",
    "RecognitionProviderError",
    "RecognitionResult",
    "RecognitionService",
    "RecognitionSkipped",
    "RecognitionStarted",
    "RecognitionStatistics",
    "RecognitionWorker",
    "UnsupportedRecognitionProviderError",
    "aggregate_recognition_results",
    "rank_character_candidates",
    "RecognitionMatcher",
    "RecognitionMatchResult",
    "RecognitionLearningStore",
    "RecognitionDisambiguator",
    "RecognitionRanker",
]


def __getattr__(name: str):
    mapping = {
        "RecognitionEngine": ("engine.recognition.recognition_engine", "RecognitionEngine"),
        "RecognitionService": ("engine.recognition.recognition_service", "RecognitionService"),
        "RecognitionWorker": ("engine.recognition.recognition_worker", "RecognitionWorker"),
        "RecognitionMatcher": ("engine.recognition.recognition_matcher", "RecognitionMatcher"),
        "RecognitionMatchResult": ("engine.recognition.recognition_matcher", "RecognitionMatchResult"),
        "RecognitionLearningStore": ("engine.recognition.recognition_learning", "RecognitionLearningStore"),
        "RecognitionDisambiguator": ("engine.recognition.recognition_disambiguation", "RecognitionDisambiguator"),
        "RecognitionRanker": ("engine.recognition.recognition_ranking", "RecognitionRanker"),
    }
    if name not in mapping:
        raise AttributeError(name)
    module_name, attribute_name = mapping[name]
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value