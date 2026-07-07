from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RelationshipType(str, Enum):
    BELONGS_TO = "belongs_to"
    ALTERNATE_NAME = "alternate_name"
    SAME_CHARACTER = "same_character"
    VARIANT = "variant"
    COSTUME = "costume"
    FORM = "form"
    PARENT = "parent"
    CHILD = "child"


class AliasKind(str, Enum):
    ALIAS = "alias"
    LOCALIZED = "localized"
    NICKNAME = "nickname"
    ALT_SPELLING = "alt_spelling"
    ABBREVIATION = "abbreviation"


class ValidationSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class WorkerTaskType(str, Enum):
    VALIDATE = "validate"
    IMPORT_CHARACTERS = "import_characters"
    IMPORT_SERIES = "import_series"
    MERGE_DATABASE = "merge_database"


class WorkerJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class AliasRecord:
    character_id: int
    value: str
    normalized_value: str
    kind: AliasKind = AliasKind.ALIAS


@dataclass(slots=True)
class CharacterRelationship:
    source_character_id: int
    target_character_id: int
    relation: RelationshipType


@dataclass(slots=True)
class CharacterRecord:
    character_id: int
    series_id: int | None
    canonical_name: str
    localized_names: list[str] = field(default_factory=list)
    japanese_name: str | None = None
    english_name: str | None = None
    romaji: str | None = None
    aliases: list[str] = field(default_factory=list)
    nicknames: list[str] = field(default_factory=list)
    alternative_spellings: list[str] = field(default_factory=list)
    abbreviations: list[str] = field(default_factory=list)
    gender: str | None = None
    description: str = ""
    relationships: list[CharacterRelationship] = field(default_factory=list)


@dataclass(slots=True)
class SeriesRecord:
    series_id: int
    canonical_title: str
    aliases: list[str] = field(default_factory=list)
    japanese_title: str | None = None
    english_title: str | None = None
    romaji: str | None = None
    franchise: str | None = None
    parent_series_id: int | None = None
    spin_off_ids: list[int] = field(default_factory=list)
    sequel_ids: list[int] = field(default_factory=list)
    prequel_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ValidationIssue:
    severity: ValidationSeverity
    code: str
    message: str


@dataclass(slots=True)
class ValidationReport:
    valid: bool
    issues: list[ValidationIssue]
    duplicate_ids: int
    duplicate_aliases: int
    broken_references: int
    circular_series_links: int
    circular_relationship_graphs: int
    invalid_aliases: int
    duplicate_canonical_names_in_series: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class WorkerProgress:
    job_id: str
    task_type: WorkerTaskType
    processed: int
    total: int
    message: str = ""


@dataclass(slots=True)
class WorkerCheckpoint:
    task_type: WorkerTaskType
    processed: int = 0
    total: int = 0


@dataclass(slots=True)
class WorkerJob:
    job_id: str
    task_type: WorkerTaskType
    status: WorkerJobStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


@dataclass(slots=True)
class DisambiguationEntry:
    character_id: int
    canonical_name: str
    series_id: int | None
    series_title: str | None
