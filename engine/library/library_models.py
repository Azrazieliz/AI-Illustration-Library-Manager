from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class LibraryHealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


class RecommendationSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True)
class LibrarySummary:
    total_images: int
    total_collections: int
    total_tags: int
    total_characters: int
    total_series: int
    total_storage_bytes: int
    missing_files: int
    broken_references: int
    orphan_records: int
    empty_collections: int
    duplicate_pairs: int
    last_scan_at: datetime | None


@dataclass(slots=True)
class LibraryDuplicateStatistics:
    total_pairs: int
    pending: int
    reviewed: int
    rejected: int
    exact: int
    perceptual: int


@dataclass(slots=True)
class LibraryTaxonomyStatistic:
    name: str
    image_count: int


@dataclass(slots=True)
class LibraryStorageStatistic:
    total_bytes: int
    average_bytes: int
    largest_bytes: int


@dataclass(slots=True)
class LibraryFolderStatistic:
    folder_path: str
    image_count: int
    total_bytes: int
    missing_files: int


@dataclass(slots=True)
class LibraryScanHistoryEntry:
    scanned_at: datetime
    images_scanned: int


@dataclass(slots=True)
class LibraryIssue:
    kind: str
    reference: str
    detail: str


@dataclass(slots=True)
class LibraryCleanupRecommendation:
    code: str
    severity: RecommendationSeverity
    message: str
    affected_count: int


@dataclass(slots=True)
class LibraryHealthReport:
    score: float
    status: LibraryHealthStatus
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LibraryStatisticsReport:
    duplicate_statistics: LibraryDuplicateStatistics
    tag_statistics: list[LibraryTaxonomyStatistic] = field(default_factory=list)
    character_statistics: list[LibraryTaxonomyStatistic] = field(default_factory=list)
    series_statistics: list[LibraryTaxonomyStatistic] = field(default_factory=list)
    storage_statistics: LibraryStorageStatistic | None = None
    folder_statistics: list[LibraryFolderStatistic] = field(default_factory=list)
    scan_history: list[LibraryScanHistoryEntry] = field(default_factory=list)


@dataclass(slots=True)
class LibraryAnalysisReport:
    summary: LibrarySummary
    health: LibraryHealthReport
    statistics: LibraryStatisticsReport
    missing_files: list[LibraryIssue] = field(default_factory=list)
    broken_references: list[LibraryIssue] = field(default_factory=list)
    orphan_records: list[LibraryIssue] = field(default_factory=list)
    empty_collections: list[LibraryIssue] = field(default_factory=list)
    cleanup_recommendations: list[LibraryCleanupRecommendation] = field(default_factory=list)
