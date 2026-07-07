from __future__ import annotations

from engine.bulk.bulk_exceptions import (
    BulkCancellationError,
    BulkException,
    BulkExecutionError,
    BulkRollbackError,
    BulkValidationError,
)
from engine.bulk.bulk_models import (
    BulkBatch,
    BulkBatchStatus,
    BulkCheckpoint,
    BulkFailure,
    BulkItem,
    BulkItemStatus,
    BulkOperationType,
    BulkProgress,
    BulkRequest,
    BulkResult,
    BulkRollbackRecord,
)
from engine.bulk.bulk_statistics import BulkStatistics

__all__ = [
    "BulkBatch",
    "BulkBatchStatus",
    "BulkCancellationError",
    "BulkCheckpoint",
    "BulkException",
    "BulkExecutionError",
    "BulkFailure",
    "BulkItem",
    "BulkItemStatus",
    "BulkOperationType",
    "BulkProgress",
    "BulkRequest",
    "BulkResult",
    "BulkRollbackRecord",
    "BulkRollbackError",
    "BulkStatistics",
    "BulkValidationError",
    "BulkEngine",
    "BulkService",
    "BulkWorker",
]


def __getattr__(name: str):
    if name == "BulkEngine":
        from engine.bulk.bulk_engine import BulkEngine

        return BulkEngine
    if name == "BulkService":
        from engine.bulk.bulk_service import BulkService

        return BulkService
    if name == "BulkWorker":
        from engine.bulk.bulk_worker import BulkWorker

        return BulkWorker
    raise AttributeError(name)
