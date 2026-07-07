from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class KnowledgeBaseDatasetStatus(str, Enum):
    """Lifecycle state for a knowledge-base dataset."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class KnowledgeBaseRecordKind(str, Enum):
    """Supported canonical record kinds."""

    DATASET = "dataset"
    SERIES = "series"
    CHARACTER = "character"
    REFERENCE_IMAGE = "reference_image"
    TRAINING_SAMPLE = "training_sample"


class KnowledgeBaseImportFormat(str, Enum):
    """Supported import/export encodings."""

    JSON = "json"
    CSV = "csv"
    YAML = "yaml"


class KnowledgeBaseTaskType(str, Enum):
    """Background worker task types."""

    IMPORT = "import"
    EXPORT = "export"
    VALIDATE = "validate"
    REBUILD = "rebuild"
    STATISTICS = "statistics"


class KnowledgeBaseJobStatus(str, Enum):
    """Lifecycle state for a worker job."""

    PENDING = "pending"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class KnowledgeBaseReferenceImage:
    """Trusted reference image for a canonical character."""

    image_id: int
    character_id: int
    path: str
    quality_score: float = 0.0
    pose_type: str | None = None
    expression: str | None = None
    outfit: str | None = None
    source: str | None = None
    approved: bool = True
    embedding_id: int | None = None
    hash_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class KnowledgeBaseTrainingSample:
    """Approved or rejected training sample for a canonical character."""

    sample_id: int
    character_id: int
    image_id: int
    approved: bool
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    confidence: float = 0.0
    source: str | None = None
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    lora_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeBaseRelationship:
    """Relationship between trusted canonical records."""

    relation: str
    target_kind: KnowledgeBaseRecordKind
    target_id: int
    confidence: float = 0.0
    notes: str = ""


@dataclass(slots=True)
class KnowledgeBaseCharacter:
    """Canonical character record used for trusted training data."""

    canonical_id: int
    dataset_id: int
    series_id: int | None
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    localized_names: list[str] = field(default_factory=list)
    romaji: str | None = None
    japanese: str | None = None
    english: str | None = None
    gender: str | None = None
    description: str = ""
    reference_images: list[KnowledgeBaseReferenceImage] = field(default_factory=list)
    approved_examples: list[KnowledgeBaseTrainingSample] = field(default_factory=list)
    relationships: list[KnowledgeBaseRelationship] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    confidence_score: float = 0.0
    training_priority: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class KnowledgeBaseSeries:
    """Canonical series record used for trusted training data."""

    canonical_id: int
    dataset_id: int
    title: str
    aliases: list[str] = field(default_factory=list)
    localized_titles: list[str] = field(default_factory=list)
    description: str = ""
    parent_series_id: int | None = None
    related_series_ids: list[int] = field(default_factory=list)
    character_ids: list[int] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class KnowledgeBaseDataset:
    """Dataset container for trusted knowledge."""

    dataset_id: int
    name: str
    description: str = ""
    version: str = "1.0"
    status: KnowledgeBaseDatasetStatus = KnowledgeBaseDatasetStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    character_count: int = 0
    series_count: int = 0
    image_count: int = 0
    alias_count: int = 0
    training_sample_count: int = 0
    reference_image_count: int = 0
    notes: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgeBaseCandidate:
    """Ranked candidate returned by knowledge-base lookups."""

    kind: KnowledgeBaseRecordKind
    record_id: int
    dataset_id: int
    name: str
    score: float
    matched_field: str = ""
    series_id: int | None = None
    series_name: str | None = None
    tags: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    fuzzy: bool = False
    unknown: bool = False


@dataclass(slots=True)
class KnowledgeBaseValidationIssue:
    """Single validation issue for a knowledge-base dataset."""

    severity: str
    code: str
    message: str


@dataclass(slots=True)
class KnowledgeBaseValidationReport:
    """Summary of validation state for knowledge-base data."""

    valid: bool
    issues: list[KnowledgeBaseValidationIssue]
    duplicate_ids: int
    duplicate_aliases: int
    missing_series: int
    broken_references: int
    duplicate_reference_images: int
    orphan_characters: int
    orphan_series: int
    invalid_datasets: int
    empty_datasets: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class KnowledgeBaseOperationResult:
    """Result payload for import/export/validation operations."""

    action: KnowledgeBaseTaskType
    success: bool
    message: str = ""
    dataset_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    progress: float = 0.0


@dataclass(slots=True)
class KnowledgeBaseCheckpoint:
    """Checkpoint for background worker resumption and cancellation."""

    processed_job_ids: set[str] = field(default_factory=set)
    cancelled_job_ids: set[str] = field(default_factory=set)

    def add_processed(self, job_id: str) -> None:
        self.processed_job_ids.add(str(job_id))

    def is_processed(self, job_id: str) -> bool:
        return str(job_id) in self.processed_job_ids

    def cancel(self, job_id: str) -> None:
        self.cancelled_job_ids.add(str(job_id))

    def resume(self, job_id: str) -> None:
        self.cancelled_job_ids.discard(str(job_id))

    def is_cancelled(self, job_id: str) -> bool:
        return str(job_id) in self.cancelled_job_ids


@dataclass(slots=True)
class KnowledgeBaseWorkerProgress:
    """Progress emitted by background worker tasks."""

    job_id: str
    task_type: KnowledgeBaseTaskType
    processed: int
    total: int
    message: str = ""


@dataclass(slots=True)
class KnowledgeBaseWorkerJob:
    """Optional internal job record for worker bookkeeping."""

    job_id: str
    task_type: KnowledgeBaseTaskType
    status: KnowledgeBaseJobStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
