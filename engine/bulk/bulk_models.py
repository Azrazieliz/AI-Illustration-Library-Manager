from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class BulkOperationType(str, Enum):
    """Known bulk operation types."""

    DELETE = "delete"
    MOVE = "move"
    COPY = "copy"
    RENAME = "rename"
    ORGANIZE = "organize"
    TAG_ASSIGN = "tag_assign"
    TAG_REMOVE = "tag_remove"
    COLLECTION_ASSIGN = "collection_assign"
    REVIEW_APPROVE = "review_approve"
    REVIEW_REJECT = "review_reject"


class BulkItemStatus(str, Enum):
    """Lifecycle state for one bulk item."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class BulkBatchStatus(str, Enum):
    """Lifecycle state for a bulk batch."""

    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass(slots=True)
class BulkRequest:
    """Normalized request for a single bulk operation."""

    operation_type: BulkOperationType
    image_ids: list[int] = field(default_factory=list)
    review_ids: list[int] = field(default_factory=list)
    target_directory: Path | None = None
    target_path: Path | None = None
    tag_name: str | None = None
    tag_category: str | None = None
    collection_id: int | None = None
    reviewer: str | None = None
    reason: str | None = None
    rename_rule: Any | None = None
    organizer_rules: list[Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BulkItem:
    """Single image or review item inside a bulk batch."""

    entity_id: int
    operation_type: BulkOperationType
    source_path: Path | None = None
    target_path: Path | None = None
    status: BulkItemStatus = BulkItemStatus.PENDING
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    batch_index: int = 0


@dataclass(slots=True)
class BulkFailure:
    """Failure detail for one bulk item."""

    entity_id: int
    operation_type: BulkOperationType
    error: str
    source_path: Path | None = None
    target_path: Path | None = None
    batch_index: int = 0


@dataclass(slots=True)
class BulkRollbackRecord:
    """Rollback metadata for one successfully applied bulk item."""

    batch_id: str
    entity_id: int
    operation_type: BulkOperationType
    source_path: Path | None = None
    target_path: Path | None = None
    previous_value: Any = None
    restored_value: Any = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BulkBatch:
    """Persistent state for one bulk batch."""

    batch_id: str = field(default_factory=lambda: str(uuid4()))
    request: BulkRequest | None = None
    items: list[BulkItem] = field(default_factory=list)
    failures: list[BulkFailure] = field(default_factory=list)
    rollback_records: list[BulkRollbackRecord] = field(default_factory=list)
    status: BulkBatchStatus = BulkBatchStatus.PENDING
    next_index: int = 0
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def processed(self) -> int:
        return sum(1 for item in self.items if item.status != BulkItemStatus.PENDING)

    @property
    def progress_percentage(self) -> float:
        if not self.items:
            return 100.0
        return round((self.processed / len(self.items)) * 100.0, 2)


@dataclass(slots=True)
class BulkResult:
    """Result payload for bulk execution, preview, or rollback."""

    batch_id: str
    operation_type: BulkOperationType
    items: list[BulkItem]
    failures: list[BulkFailure]
    dry_run: bool
    applied: bool
    rolled_back: bool = False
    cancelled: bool = False
    resumed: bool = False
    status: BulkBatchStatus = BulkBatchStatus.PENDING
    rollback_records: list[BulkRollbackRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def processed(self) -> int:
        return sum(1 for item in self.items if item.status != BulkItemStatus.PENDING)

    @property
    def succeeded(self) -> int:
        return sum(1 for item in self.items if item.status == BulkItemStatus.SUCCEEDED)

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def skipped(self) -> int:
        return sum(1 for item in self.items if item.status == BulkItemStatus.SKIPPED)

    @property
    def progress_percentage(self) -> float:
        if not self.items:
            return 100.0
        return round((self.processed / len(self.items)) * 100.0, 2)


@dataclass(slots=True)
class BulkProgress:
    """Progress report for one step of a bulk batch."""

    batch_id: str
    operation_type: BulkOperationType
    processed: int
    total: int
    percent: float
    entity_id: int | None = None
    batch_index: int = 0


@dataclass(slots=True)
class BulkCheckpoint:
    """Checkpoint for resuming bulk batches."""

    processed_batches: set[str] = field(default_factory=set)

    def add_processed(self, batch_id: str) -> None:
        self.processed_batches.add(batch_id)

    def is_processed(self, batch_id: str) -> bool:
        return batch_id in self.processed_batches
