from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class IntegritySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IntegrityCheckName(str, Enum):
    MISSING_IMAGE_FILES = "missing_image_files"
    MISSING_THUMBNAILS = "missing_thumbnails"
    MISSING_METADATA = "missing_metadata"
    MISSING_EMBEDDINGS = "missing_embeddings"
    MISSING_KNOWLEDGE_GRAPH_ENTRIES = "missing_knowledge_graph_entries"
    MISSING_SEARCH_INDEX = "missing_search_index"
    MISSING_TAGS = "missing_tags"
    ORPHAN_METADATA = "orphan_metadata"
    ORPHAN_EMBEDDINGS = "orphan_embeddings"
    ORPHAN_THUMBNAILS = "orphan_thumbnails"
    ORPHAN_KNOWLEDGE_GRAPH_NODES = "orphan_knowledge_graph_nodes"
    BROKEN_CHARACTER_REFERENCES = "broken_character_references"
    BROKEN_SERIES_REFERENCES = "broken_series_references"
    BROKEN_COLLECTION_REFERENCES = "broken_collection_references"
    BROKEN_REVIEW_REFERENCES = "broken_review_references"
    BROKEN_RENAME_HISTORY = "broken_rename_history"
    BROKEN_ORGANIZER_HISTORY = "broken_organizer_history"
    DUPLICATE_UUID_DETECTION = "duplicate_uuid_detection"
    DUPLICATE_DATABASE_IDS = "duplicate_database_ids"
    INVALID_PATHS = "invalid_paths"
    CASE_COLLISION_DETECTION = "case_collision_detection"
    RESERVED_FILENAME_DETECTION = "reserved_filename_detection"
    FILENAME_VALIDATION = "filename_validation"
    DATABASE_CONSISTENCY = "database_consistency"
    PIPELINE_CONSISTENCY = "pipeline_consistency"
    COLLECTION_CONSISTENCY = "collection_consistency"
    RECOGNITION_CONSISTENCY = "recognition_consistency"
    STATISTICS_CONSISTENCY = "statistics_consistency"
    DATASET_CONSISTENCY = "dataset_consistency"
    EXPORT_CONSISTENCY = "export_consistency"


@dataclass(slots=True)
class IntegrityIssue:
    severity: IntegritySeverity
    subsystem: str
    description: str
    image_id: int | None = None
    file_path: str | None = None
    suggested_repair: str = "Manual investigation required."


@dataclass(slots=True)
class IntegrityCheckResult:
    check_name: IntegrityCheckName
    passed: bool
    duration_seconds: float
    issues: list[IntegrityIssue] = field(default_factory=list)


@dataclass(slots=True)
class IntegritySummary:
    checks_performed: int
    passed_checks: int
    failed_checks: int
    issues_found: int
    warnings: int
    errors: int
    critical_errors: int


@dataclass(slots=True)
class IntegrityReport:
    check_results: list[IntegrityCheckResult]
    passed_checks: list[IntegrityCheckName]
    failed_checks: list[IntegrityCheckName]
    warnings: list[IntegrityIssue]
    errors: list[IntegrityIssue]
    execution_time_seconds: float
    summary: IntegritySummary
    cancelled: bool = False
    resumed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class IntegrityProgress:
    scan_id: str
    completed_checks: int
    total_checks: int
    current_check: IntegrityCheckName | None = None
    cancelled: bool = False


@dataclass(slots=True)
class IntegrityCheckpoint:
    completed_checks: set[IntegrityCheckName] = field(default_factory=set)

    def add(self, check: IntegrityCheckName) -> None:
        self.completed_checks.add(check)

    def contains(self, check: IntegrityCheckName) -> bool:
        return check in self.completed_checks
