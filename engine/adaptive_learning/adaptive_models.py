from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AdaptiveLearningSource(str, Enum):
    APPROVED_REVIEW = "approved_review"
    REJECTED_REVIEW = "rejected_review"
    MANUAL_CHARACTER_CORRECTION = "manual_character_correction"
    MANUAL_SERIES_CORRECTION = "manual_series_correction"
    RENAME_HISTORY = "rename_history"
    ORGANIZER_HISTORY = "organizer_history"
    TAG_EDIT = "tag_edit"
    COLLECTION_EDIT = "collection_edit"
    DUPLICATE_MERGE_DECISION = "duplicate_merge_decision"
    KNOWLEDGE_PACK_UPDATE = "knowledge_pack_update"
    EXTERNAL_CANONICAL_DATABASE = "external_canonical_database"


class AdaptiveTaskType(str, Enum):
    INCREMENTAL_TRAIN = "incremental_train"
    ROLLBACK = "rollback"


class AdaptiveTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(slots=True)
class AdaptiveConfidenceWeights:
    review_history: float = 0.15
    previous_approvals: float = 0.10
    previous_rejections: float = 0.10
    knowledge_pack_confidence: float = 0.10
    embedding_similarity: float = 0.15
    filename_similarity: float = 0.10
    folder_similarity: float = 0.05
    relationship_graph: float = 0.10
    series_probability: float = 0.05
    user_correction_history: float = 0.05
    historical_precision: float = 0.05

    def normalized(self) -> dict[str, float]:
        values = asdict(self)
        total = sum(max(0.0, float(item)) for item in values.values())
        if total <= 0.0:
            count = len(values)
            return {key: 1.0 / float(count) for key in values}
        return {key: max(0.0, float(value)) / total for key, value in values.items()}


@dataclass(slots=True)
class AdaptiveEvidence:
    source: AdaptiveLearningSource
    canonical_character_id: str
    canonical_series_id: str
    confidence: float = 0.0
    accepted: bool = False
    rejected: bool = False
    false_positive: bool = False
    false_negative: bool = False
    embedding_key: str | None = None
    embedding_vector: list[float] = field(default_factory=list)
    visual_fingerprint: str | None = None
    filename_pattern: str | None = None
    folder_pattern: str | None = None
    aliases: list[str] = field(default_factory=list)
    pose: str | None = None
    hairstyle: str | None = None
    clothing: str | None = None
    dominant_palette: str | None = None
    accessories: list[str] = field(default_factory=list)
    co_occurring_characters: list[str] = field(default_factory=list)
    co_occurring_series: list[str] = field(default_factory=list)
    relationships: list[tuple[str, str]] = field(default_factory=list)
    knowledge_pack_confidence: float = 0.0
    embedding_similarity: float = 0.0
    filename_similarity: float = 0.0
    folder_similarity: float = 0.0
    series_probability: float = 0.0
    ambiguity: float = 0.0
    rare_character: bool = False
    unseen_alias: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class CharacterLearningProfile:
    canonical_character_id: str
    canonical_series_id: str
    confidence_history: list[float] = field(default_factory=list)
    accepted_matches: int = 0
    rejected_matches: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    embedding_history: dict[str, list[float]] = field(default_factory=dict)
    visual_fingerprint_history: list[str] = field(default_factory=list)
    filename_patterns: dict[str, int] = field(default_factory=dict)
    folder_patterns: dict[str, int] = field(default_factory=dict)
    alias_usage: dict[str, int] = field(default_factory=dict)
    pose_frequency: dict[str, int] = field(default_factory=dict)
    hairstyle_frequency: dict[str, int] = field(default_factory=dict)
    clothing_frequency: dict[str, int] = field(default_factory=dict)
    dominant_color_palette: dict[str, int] = field(default_factory=dict)
    accessory_frequency: dict[str, int] = field(default_factory=dict)
    co_occurring_characters: dict[str, int] = field(default_factory=dict)
    co_occurring_series: dict[str, int] = field(default_factory=dict)
    relationship_graph: dict[str, int] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    learning_score: float = 0.0


@dataclass(slots=True)
class AdaptiveCandidate:
    canonical_character_id: str
    canonical_series_id: str
    canonical_name: str
    base_confidence: float
    features: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class AdaptiveConfidenceResult:
    canonical_character_id: str
    canonical_series_id: str
    score: float
    components: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class AdaptiveUncertaintyItem:
    evidence_id: str
    canonical_character_id: str
    canonical_series_id: str
    confidence: float
    ambiguity: float
    rare_character: bool
    unseen_alias: bool

    @property
    def priority(self) -> tuple[float, float, int, int]:
        return (
            self.confidence,
            -self.ambiguity,
            -int(self.rare_character),
            -int(self.unseen_alias),
        )


@dataclass(slots=True)
class AdaptiveCheckpoint:
    job_id: str
    task_type: AdaptiveTaskType
    status: AdaptiveTaskStatus = AdaptiveTaskStatus.PENDING
    stage: str = "queued"
    processed_events: int = 0
    progress: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class AdaptiveProgress:
    job_id: str
    task_type: AdaptiveTaskType
    status: AdaptiveTaskStatus
    progress: int
    message: str = ""


@dataclass(slots=True)
class AdaptiveLearningResult:
    action: str
    success: bool
    details: dict[str, Any] = field(default_factory=dict)
    message: str = ""
