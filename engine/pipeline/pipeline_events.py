from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.pipeline.pipeline_models import PipelineJob, QueueType


@dataclass(slots=True)
class JobQueued:
    """Raised when a job is enqueued."""

    job: PipelineJob
    queue_type: QueueType
    payload: dict[str, Any] | None = None


@dataclass(slots=True)
class JobStarted:
    """Raised when a job begins processing."""

    job: PipelineJob
    queue_type: QueueType


@dataclass(slots=True)
class JobFinished:
    """Raised when a job finishes successfully."""

    job: PipelineJob
    queue_type: QueueType


@dataclass(slots=True)
class JobFailed:
    """Raised when a job fails processing."""

    job: PipelineJob
    queue_type: QueueType
    error_message: str


@dataclass(slots=True)
class QueuePaused:
    """Raised when a queue is paused."""

    queue_type: QueueType


@dataclass(slots=True)
class QueueResumed:
    """Raised when a queue is resumed."""

    queue_type: QueueType
