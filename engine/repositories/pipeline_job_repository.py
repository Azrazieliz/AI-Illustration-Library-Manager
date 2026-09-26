from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from engine.database.base import utcnow
from engine.database.models.pipeline_job import PipelineJobRecord
from engine.database.session import session_scope
from engine.pipeline.pipeline_models import PipelineJob, PipelineJobStatus, QueueType


class PipelineJobRepository:
    """Transactional persistence gateway for pipeline execution state."""

    _RECOVERABLE_STATUSES = (
        PipelineJobStatus.PENDING.value,
        PipelineJobStatus.RUNNING.value,
        PipelineJobStatus.PAUSED.value,
    )

    def persist_enqueued(self, job: PipelineJob, queue_type: QueueType) -> None:
        with session_scope() as session:
            record = self._get_or_create(session, job)
            record.queue = queue_type.value
            record.stage = self._stage(job, queue_type)
            record.priority = job.priority
            record.status = PipelineJobStatus.PENDING.value
            record.retry_count = job.retry_count
            record.max_retry = job.max_retries
            record.input_payload = self._input_payload(job)
            record.output_payload = self._payload_or_none(job.output_payload, "output_payload")
            record.error_log = None
            record.worker = job.worker
            record.started_at = None
            record.finished_at = None

    def mark_running(self, job: PipelineJob, queue_type: QueueType) -> None:
        with session_scope() as session:
            record = self._require_record(session, job)
            record.queue = queue_type.value
            record.status = PipelineJobStatus.RUNNING.value
            record.worker = job.worker
            record.started_at = record.started_at or utcnow()
            record.finished_at = None

    def mark_completed(self, job: PipelineJob, queue_type: QueueType) -> None:
        with session_scope() as session:
            record = self._require_record(session, job)
            record.queue = queue_type.value
            record.status = PipelineJobStatus.COMPLETED.value
            record.retry_count = job.retry_count
            record.output_payload = self._payload_or_none(job.output_payload, "output_payload")
            record.error_log = None
            record.worker = job.worker
            record.finished_at = utcnow()

    def mark_failed(self, job: PipelineJob, queue_type: QueueType, error_message: str) -> None:
        with session_scope() as session:
            record = self._require_record(session, job)
            record.queue = queue_type.value
            record.status = PipelineJobStatus.FAILED.value
            record.retry_count = job.retry_count
            record.error_log = str(error_message)
            record.worker = job.worker
            record.finished_at = utcnow()

    def mark_cancelled(self, job: PipelineJob, queue_type: QueueType) -> None:
        with session_scope() as session:
            record = self._require_record(session, job)
            record.queue = queue_type.value
            record.status = PipelineJobStatus.CANCELLED.value
            record.retry_count = job.retry_count
            record.worker = job.worker
            record.finished_at = utcnow()

    def recover_unfinished(self) -> list[PipelineJob]:
        with session_scope() as session:
            records = list(
                session.query(PipelineJobRecord)
                .filter(PipelineJobRecord.status.in_(self._RECOVERABLE_STATUSES))
                .order_by(PipelineJobRecord.created_at.asc(), PipelineJobRecord.id.asc())
            )
            jobs = [self._to_pipeline_job(record) for record in records]
            for record in records:
                record.status = PipelineJobStatus.PENDING.value
                record.worker = None
                record.finished_at = None
            return jobs

    @staticmethod
    def _get_or_create(session: Any, job: PipelineJob) -> PipelineJobRecord:
        record = session.query(PipelineJobRecord).filter(PipelineJobRecord.uuid == str(job.id)).one_or_none()
        if record is None:
            record = PipelineJobRecord(uuid=str(job.id), input_payload={})
            session.add(record)
        return record

    @staticmethod
    def _require_record(session: Any, job: PipelineJob) -> PipelineJobRecord:
        record = session.query(PipelineJobRecord).filter(PipelineJobRecord.uuid == str(job.id)).one_or_none()
        if record is None:
            raise ValueError(f"Pipeline job is not persisted: {job.id}")
        return record

    @classmethod
    def _input_payload(cls, job: PipelineJob) -> dict[str, Any]:
        return {
            "source_path": job.source_path,
            "metadata": cls._validate_payload(job.metadata, "metadata"),
        }

    @staticmethod
    def _stage(job: PipelineJob, queue_type: QueueType) -> str:
        if queue_type is not QueueType.SEARCH:
            return queue_type.value
        stage = job.metadata.get("stage", "search")
        if not isinstance(stage, str) or not stage.strip():
            raise ValueError("SEARCH pipeline jobs require a non-empty string metadata.stage")
        return stage.strip()

    @classmethod
    def _payload_or_none(cls, payload: dict[str, Any] | None, field_name: str) -> dict[str, Any] | None:
        return None if payload is None else cls._validate_payload(payload, field_name)

    @classmethod
    def _validate_payload(cls, payload: Any, field_name: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        cls._validate_json_value(payload, field_name)
        return payload

    @classmethod
    def _validate_json_value(cls, value: Any, field_name: str) -> None:
        if value is None or isinstance(value, (str, bool, int)):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"{field_name} contains a non-finite number")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                cls._validate_json_value(item, f"{field_name}[{index}]")
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{field_name} contains a non-string object key")
                cls._validate_json_value(item, f"{field_name}.{key}")
            return
        raise ValueError(f"{field_name} contains unsupported value type {type(value).__name__}")

    @staticmethod
    def _to_pipeline_job(record: PipelineJobRecord) -> PipelineJob:
        try:
            queue_type = QueueType(record.queue)
            status = PipelineJobStatus(record.status)
            job_id = UUID(record.uuid)
        except ValueError as error:
            raise ValueError(f"Persisted pipeline job {record.uuid} has an invalid queue state: {error}") from error

        payload = record.input_payload
        if not isinstance(payload, dict):
            raise ValueError(f"Persisted pipeline job {record.uuid} has an invalid input_payload")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"Persisted pipeline job {record.uuid} has a non-object metadata payload")
        source_path = payload.get("source_path")
        if source_path is not None and not isinstance(source_path, str):
            raise ValueError(f"Persisted pipeline job {record.uuid} has a non-string source_path")

        return PipelineJob(
            id=job_id,
            creation_time=record.created_at,
            queue_type=queue_type,
            priority=record.priority,
            status=status,
            source_path=source_path,
            metadata=metadata,
            retry_count=record.retry_count,
            max_retries=record.max_retry,
            worker=record.worker,
            error_message=record.error_log,
            output_payload=record.output_payload,
        )