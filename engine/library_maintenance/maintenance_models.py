from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MaintenanceTaskType(str, Enum):
    REBUILD_THUMBNAILS = "rebuild_thumbnails"
    REGENERATE_METADATA = "regenerate_metadata"
    RECOMPUTE_EMBEDDINGS = "recompute_embeddings"
    REBUILD_SEARCH_INDEX = "rebuild_search_index"
    REBUILD_KNOWLEDGE_GRAPH = "rebuild_knowledge_graph"
    RECOMPUTE_HASHES = "recompute_hashes"
    REMOVE_ORPHAN_METADATA = "remove_orphan_metadata"
    REMOVE_ORPHAN_EMBEDDINGS = "remove_orphan_embeddings"
    REMOVE_ORPHAN_THUMBNAILS = "remove_orphan_thumbnails"
    REMOVE_ORPHAN_KNOWLEDGE_GRAPH = "remove_orphan_knowledge_graph"
    REPAIR_BROKEN_CHARACTER_REFERENCES = "repair_broken_character_references"
    REPAIR_BROKEN_SERIES_REFERENCES = "repair_broken_series_references"
    REPAIR_COLLECTION_HIERARCHY = "repair_collection_hierarchy"
    REPAIR_REVIEW_REFERENCES = "repair_review_references"
    REPAIR_ORGANIZER_HISTORY = "repair_organizer_history"
    REPAIR_RENAME_HISTORY = "repair_rename_history"
    RECALCULATE_LIBRARY_STATISTICS = "recalculate_library_statistics"
    RECALCULATE_DUPLICATE_CACHE = "recalculate_duplicate_cache"
    RECALCULATE_TAG_STATISTICS = "recalculate_tag_statistics"
    REBUILD_DATASET_INDEXES = "rebuild_dataset_indexes"
    VALIDATE_EXPORT_MANIFESTS = "validate_export_manifests"
    REMOVE_TEMPORARY_FILES = "remove_temporary_files"
    CLEAN_STALE_CACHES = "clean_stale_caches"
    VACUUM_OPTIMIZE_DATABASE = "vacuum_optimize_database"
    COMPACT_INTERNAL_INDEXES = "compact_internal_indexes"
    REMOVE_INVALID_QUEUE_ENTRIES = "remove_invalid_queue_entries"
    RETRY_INTERRUPTED_MAINTENANCE_JOBS = "retry_interrupted_maintenance_jobs"


class MaintenanceJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class MaintenanceWarning:
    task: MaintenanceTaskType
    message: str


@dataclass(slots=True)
class MaintenanceError:
    task: MaintenanceTaskType
    message: str


@dataclass(slots=True)
class MaintenanceResult:
    task: MaintenanceTaskType
    repaired_items: int = 0
    skipped_items: int = 0
    failed_items: int = 0
    warnings: list[MaintenanceWarning] = field(default_factory=list)
    duration_seconds: float = 0.0
    rolled_back: bool = False


@dataclass(slots=True)
class MaintenanceTaskPlan:
    task: MaintenanceTaskType
    preview: bool = False
    dry_run: bool = False


@dataclass(slots=True)
class MaintenanceJob:
    job_id: str
    job_type: str
    status: MaintenanceJobStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: int = 0
    affected_items: int = 0
    errors: list[str] = field(default_factory=list)
    completed_tasks: set[MaintenanceTaskType] = field(default_factory=set)


@dataclass(slots=True)
class MaintenanceSummary:
    total_tasks: int
    repaired_items: int
    skipped_items: int
    failed_items: int
    warnings: int


@dataclass(slots=True)
class MaintenanceReport:
    job: MaintenanceJob
    results: list[MaintenanceResult]
    summary: MaintenanceSummary
    execution_time_seconds: float
    dry_run: bool = False
    preview: bool = False
    resumed: bool = False
    cancelled: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class MaintenanceProgress:
    job_id: str
    completed_tasks: int
    total_tasks: int
    current_task: MaintenanceTaskType | None = None
    progress: int = 0


@dataclass(slots=True)
class MaintenanceRollbackRecord:
    task: MaintenanceTaskType
    data: dict


@dataclass(slots=True)
class MaintenanceCheckpoint:
    completed_tasks: set[MaintenanceTaskType] = field(default_factory=set)

    def add(self, task: MaintenanceTaskType) -> None:
        self.completed_tasks.add(task)

    def contains(self, task: MaintenanceTaskType) -> bool:
        return task in self.completed_tasks
