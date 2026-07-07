from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class PipelineJobStatus(str, Enum):
    """Lifecycle state for a queued pipeline job."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class QueueType(str, Enum):
    """Known queue types in the pipeline."""

    DISCOVERY = "discovery"
    INDEX = "index"
    HASH = "hash"
    DUPLICATE = "duplicate"
    THUMBNAIL = "thumbnail"
    EMBEDDING = "embedding"
    RECOGNITION = "recognition"
    REVIEW = "review"
    METADATA = "metadata"
    TRANSACTION = "transaction"


@dataclass(slots=True)
class PipelineJob:
    """A unit of work published into a pipeline queue."""

    id: UUID = field(default_factory=uuid4)
    creation_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    queue_type: QueueType = QueueType.DISCOVERY
    priority: int = 0
    status: PipelineJobStatus = PipelineJobStatus.PENDING
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    worker: str | None = None
    error_message: str | None = None
