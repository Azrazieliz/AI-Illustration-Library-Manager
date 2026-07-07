from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class ReviewStatus(str, Enum):
    """Lifecycle state for a review item."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class ReviewDecisionType(str, Enum):
    """Supported decision types for review items."""

    APPROVE = "approve"
    REJECT = "reject"
    SKIP = "skip"


@dataclass(slots=True)
class ReviewItem:
    """Manual validation item for a suspected recognition, rename, or organization change."""

    review_id: int = 0
    item_uuid: str = field(default_factory=lambda: str(uuid4()))
    image_id: int = 0
    source_path: Path = field(default_factory=Path)
    operation_type: str = "unknown"
    confidence: float = 0.0
    proposed_value: Any = None
    current_value: Any = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: ReviewStatus = ReviewStatus.PENDING
    reviewer: str | None = None
    decision_reason: str | None = None
    series: str | None = None
    character: str | None = None
    batch_id: str | None = None


@dataclass(slots=True)
class ReviewDecision:
    """Stores one review decision together with rollback metadata."""

    review_id: int
    decision: ReviewDecisionType
    previous_status: ReviewStatus
    new_status: ReviewStatus
    previous_value: Any
    new_value: Any
    reviewer: str | None = None
    reason: str | None = None
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    batch_id: str | None = None


@dataclass(slots=True)
class ReviewBatch:
    """Group of review items and decisions handled together."""

    batch_id: str
    items: list[ReviewItem]
    decisions: list[ReviewDecision] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class ReviewResult:
    """Result payload for review operations."""

    batch_id: str
    items: list[ReviewItem]
    decisions: list[ReviewDecision]
    dry_run: bool
    applied: bool
    rolled_back: bool = False
    skipped: int = 0
    failed: int = 0


@dataclass(slots=True)
class ReviewSearchResult:
    """Paginated review search output."""

    items: list[ReviewItem]
    total: int
    page: int
    page_size: int


@dataclass(slots=True)
class ReviewCheckpoint:
    """Checkpoint for review queue processing."""

    processed_items: set[int] = field(default_factory=set)

    def add_processed(self, review_id: int) -> None:
        self.processed_items.add(review_id)

    def is_processed(self, review_id: int) -> bool:
        return review_id in self.processed_items
