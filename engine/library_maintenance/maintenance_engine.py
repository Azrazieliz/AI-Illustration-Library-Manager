from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from engine.embeddings import EmbeddingService
from engine.database.models.embedding import Embedding
from engine.library_maintenance.maintenance_builder import MaintenanceBuilder
from engine.library_maintenance.maintenance_models import (
    MaintenanceCheckpoint,
    MaintenanceError,
    MaintenanceJob,
    MaintenanceJobStatus,
    MaintenanceProgress,
    MaintenanceReport,
    MaintenanceResult,
    MaintenanceRollbackRecord,
    MaintenanceTaskType,
    MaintenanceWarning,
)
from engine.library_maintenance.maintenance_statistics import MaintenanceStatistics
from engine.pipeline import PipelineJob, QueueType
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.maintenance_repository import MaintenanceRepository


class LibraryMaintenanceEngine:
    """Executes library repair and maintenance tasks."""

    def __init__(
        self,
        *,
        repository: MaintenanceRepository | None = None,
        builder: MaintenanceBuilder | None = None,
        embedding_service: EmbeddingService | None = None,
        callback=None,
    ) -> None:
        self.repository = repository or MaintenanceRepository()
        self.builder = builder or MaintenanceBuilder()
        self.embedding_service = embedding_service or EmbeddingService()
        self.callback = callback
        self.statistics = MaintenanceStatistics()
        self._jobs: dict[str, MaintenanceJob] = {}
        self._job_tasks: dict[str, list[MaintenanceTaskType]] = {}
        self._checkpoints: dict[str, MaintenanceCheckpoint] = {}
        self._cancel_requested: set[str] = set()
        self._rollback_records: dict[str, list[MaintenanceRollbackRecord]] = {}
        self._load_state()

    def run_full_maintenance(self, *, preview: bool = False, dry_run: bool = False, job_id: str | None = None, resumed: bool = False) -> MaintenanceReport:
        tasks = [item for item in MaintenanceTaskType]
        return self.run_selected_tasks(tasks, preview=preview, dry_run=dry_run, job_id=job_id, resumed=resumed)

    def preview_repairs(self, tasks: list[MaintenanceTaskType] | None = None) -> MaintenanceReport:
        selected = tasks or [item for item in MaintenanceTaskType]
        return self.run_selected_tasks(selected, preview=True, dry_run=True)

    def run_selected_tasks(
        self,
        tasks: list[MaintenanceTaskType],
        *,
        preview: bool = False,
        dry_run: bool = False,
        job_id: str | None = None,
        resumed: bool = False,
    ) -> MaintenanceReport:
        resolved_id = job_id or str(uuid4())
        selected = list(tasks)
        checkpoint = self._checkpoints.get(resolved_id, MaintenanceCheckpoint())
        job = self._jobs.get(resolved_id)
        if job is None:
            job = MaintenanceJob(
                job_id=resolved_id,
                job_type="selected" if len(selected) < len(MaintenanceTaskType) else "full",
                status=MaintenanceJobStatus.PENDING,
            )
            self._jobs[resolved_id] = job
        self._job_tasks.setdefault(resolved_id, list(selected))
        self._rollback_records.setdefault(resolved_id, [])
        self._persist_state()

        started = perf_counter()
        results: list[MaintenanceResult] = []
        total = len(selected)

        job.status = MaintenanceJobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        self._persist_state()
        cancelled = False

        completed = len([item for item in selected if checkpoint.contains(item)])
        for task in selected:
            if checkpoint.contains(task):
                continue
            if resolved_id in self._cancel_requested:
                cancelled = True
                break

            self._emit(
                MaintenanceProgress(
                    job_id=resolved_id,
                    completed_tasks=completed,
                    total_tasks=total,
                    current_task=task,
                    progress=int((completed / max(1, total)) * 100),
                )
            )

            task_started = perf_counter()
            result = self._execute_task(task, preview=preview, dry_run=dry_run, job_id=resolved_id)
            result.duration_seconds = perf_counter() - task_started
            results.append(result)

            checkpoint.add(task)
            job.completed_tasks.add(task)
            completed += 1
            job.progress = int((completed / max(1, total)) * 100)
            self._checkpoints[resolved_id] = checkpoint
            self._persist_state()

        job.finished_at = datetime.now(timezone.utc)
        if cancelled:
            job.status = MaintenanceJobStatus.CANCELLED
            self._cancel_requested.discard(resolved_id)
        elif any(item.failed_items > 0 for item in results):
            job.status = MaintenanceJobStatus.FAILED
        else:
            job.status = MaintenanceJobStatus.COMPLETED

        job.affected_items = sum(item.repaired_items + item.skipped_items + item.failed_items for item in results)
        self._checkpoints[resolved_id] = checkpoint
        self._persist_state()

        report = self.builder.build_report(
            job=job,
            results=results,
            execution_time_seconds=perf_counter() - started,
            dry_run=dry_run,
            preview=preview,
            resumed=resumed,
            cancelled=cancelled,
        )
        self.builder.build_statistics(existing=self.statistics, report=report)

        self._emit(
            MaintenanceProgress(
                job_id=resolved_id,
                completed_tasks=completed,
                total_tasks=total,
                current_task=None,
                progress=job.progress,
            )
        )
        return report

    def cancel_job(self, job_id: str) -> None:
        self._cancel_requested.add(job_id)
        if job_id in self._jobs:
            self._jobs[job_id].status = MaintenanceJobStatus.CANCELLED
            self._persist_state()

    def resume_job(self, job_id: str) -> MaintenanceReport:
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Maintenance job not found: {job_id}")
        planned_tasks = self._job_tasks.get(job_id, list(MaintenanceTaskType))
        remaining = [task for task in planned_tasks if task not in self._checkpoints.get(job_id, MaintenanceCheckpoint()).completed_tasks]
        if not remaining:
            return self.run_selected_tasks([], job_id=job_id, resumed=True)
        return self.run_selected_tasks(remaining, job_id=job_id, resumed=True)

    def rollback_job(self, job_id: str) -> int:
        records = self._rollback_records.get(job_id, [])
        restored = 0
        while records:
            record = records[-1]
            if record.task == MaintenanceTaskType.REMOVE_ORPHAN_METADATA:
                payload = record.data
                self.repository.metadata_repository.create_metadata_record(
                    image_id=payload["image_id"],
                    mime_type=payload.get("mime_type"),
                    exif_data=payload.get("exif_data"),
                )
                restored += 1
            elif record.task == MaintenanceTaskType.REMOVE_ORPHAN_EMBEDDINGS:
                payload = record.data
                self.repository.session.add(Embedding(
                    id=payload["id"],
                    uuid=payload["uuid"],
                    created_at=payload["created_at"],
                    updated_at=payload["updated_at"],
                    image_id=payload["image_id"],
                    vector_path=payload["vector_path"],
                    model_name=payload["model_name"],
                    model_version=payload["model_version"],
                    image_uuid=payload["image_uuid"],
                    dimension=payload["dimension"],
                    dtype=payload["dtype"],
                    storage_path=payload["storage_path"],
                    checksum=payload["checksum"],
                    version=payload["version"],
                ))
                self.repository.session.commit()
                restored += 1
            elif record.task == MaintenanceTaskType.REMOVE_ORPHAN_THUMBNAILS:
                payload = record.data
                self.repository.thumbnail_repository.create_thumbnail_record(
                    image_id=payload["image_id"],
                    size=payload.get("size", 256),
                    format=payload.get("format", "webp"),
                    file_path=payload["file_path"],
                    file_size_bytes=payload.get("file_size_bytes", 0),
                    cache_key=payload.get("cache_key", f"restored-{payload['image_id']}"),
                    thumb_width=payload.get("thumb_width", 64),
                    thumb_height=payload.get("thumb_height", 64),
                )
                restored += 1
            records.pop()
            self._persist_state()
        return restored

    def _append_rollback_record(self, job_id: str, record: MaintenanceRollbackRecord) -> None:
        self._rollback_records.setdefault(job_id, []).append(record)
        self._persist_state()

    def _load_state(self) -> None:
        load_state = getattr(self.repository, "load_maintenance_state", None)
        if not callable(load_state):
            return
        payload = load_state()
        if payload is None:
            return
        self._restore_state(payload)
        interrupted = False
        for job in self._jobs.values():
            if job.status is MaintenanceJobStatus.RUNNING:
                job.status = MaintenanceJobStatus.PAUSED
                interrupted = True
        if interrupted:
            self._persist_state()

    def _persist_state(self) -> None:
        save_state = getattr(self.repository, "save_maintenance_state", None)
        if callable(save_state):
            save_state(self._state_payload())

    def _state_payload(self) -> dict[str, Any]:
        return {
            "jobs": {
                job_id: {
                    "job_id": job.job_id,
                    "job_type": job.job_type,
                    "status": job.status.value,
                    "started_at": self._datetime_value(job.started_at),
                    "finished_at": self._datetime_value(job.finished_at),
                    "progress": job.progress,
                    "affected_items": job.affected_items,
                    "errors": list(job.errors),
                    "completed_tasks": [task.value for task in sorted(job.completed_tasks, key=lambda item: item.value)],
                }
                for job_id, job in sorted(self._jobs.items())
            },
            "job_tasks": {
                job_id: [task.value for task in tasks]
                for job_id, tasks in sorted(self._job_tasks.items())
            },
            "checkpoints": {
                job_id: [task.value for task in sorted(checkpoint.completed_tasks, key=lambda item: item.value)]
                for job_id, checkpoint in sorted(self._checkpoints.items())
            },
            "rollback_records": {
                job_id: [
                    {"task": record.task.value, "data": self._json_value(record.data)}
                    for record in records
                ]
                for job_id, records in sorted(self._rollback_records.items())
            },
        }

    def _restore_state(self, payload: dict[str, Any]) -> None:
        jobs = payload.get("jobs", {})
        job_tasks = payload.get("job_tasks", {})
        checkpoints = payload.get("checkpoints", {})
        rollback_records = payload.get("rollback_records", {})
        if not all(isinstance(value, dict) for value in (jobs, job_tasks, checkpoints, rollback_records)):
            raise RuntimeError("Persisted maintenance state is invalid")

        self._jobs = {
            str(job_id): self._job_from_payload(item)
            for job_id, item in jobs.items()
            if isinstance(item, dict)
        }
        self._job_tasks = {
            str(job_id): self._task_list_from_payload(tasks)
            for job_id, tasks in job_tasks.items()
        }
        self._checkpoints = {
            str(job_id): MaintenanceCheckpoint(completed_tasks=set(self._task_list_from_payload(tasks)))
            for job_id, tasks in checkpoints.items()
        }
        self._rollback_records = {
            str(job_id): [
                self._rollback_record_from_payload(record)
                for record in records
                if isinstance(record, dict)
            ]
            for job_id, records in rollback_records.items()
            if isinstance(records, list)
        }
        for job_id in self._jobs:
            self._job_tasks.setdefault(job_id, list(MaintenanceTaskType))
            self._checkpoints.setdefault(job_id, MaintenanceCheckpoint())
            self._rollback_records.setdefault(job_id, [])

    @classmethod
    def _job_from_payload(cls, payload: dict[str, Any]) -> MaintenanceJob:
        return MaintenanceJob(
            job_id=str(payload.get("job_id", "")),
            job_type=str(payload.get("job_type", "selected")),
            status=MaintenanceJobStatus(str(payload.get("status", MaintenanceJobStatus.PENDING.value))),
            started_at=cls._as_utc(payload.get("started_at")),
            finished_at=cls._as_utc(payload.get("finished_at")),
            progress=int(payload.get("progress", 0)),
            affected_items=int(payload.get("affected_items", 0)),
            errors=[str(item) for item in payload.get("errors", [])],
            completed_tasks=set(cls._task_list_from_payload(payload.get("completed_tasks", []))),
        )

    @classmethod
    def _rollback_record_from_payload(cls, payload: dict[str, Any]) -> MaintenanceRollbackRecord:
        data = dict(payload.get("data", {}))
        for field_name in ("created_at", "updated_at"):
            if field_name in data:
                data[field_name] = cls._as_utc(data[field_name])
        return MaintenanceRollbackRecord(
            task=MaintenanceTaskType(str(payload.get("task", ""))),
            data=data,
        )

    @staticmethod
    def _task_list_from_payload(payload: Any) -> list[MaintenanceTaskType]:
        if not isinstance(payload, list):
            raise RuntimeError("Persisted maintenance task list is invalid")
        return [MaintenanceTaskType(str(item)) for item in payload]

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, datetime):
            return cls._datetime_value(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {str(key): cls._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        raise ValueError(f"Maintenance state values must be JSON-compatible, got {type(value).__name__}")

    @staticmethod
    def _datetime_value(value: datetime | None) -> str | None:
        return None if value is None else value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _as_utc(value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            raise RuntimeError("Persisted maintenance timestamp is invalid") from None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    def _execute_task(self, task: MaintenanceTaskType, *, preview: bool, dry_run: bool, job_id: str) -> MaintenanceResult:
        if preview:
            return self._preview_task(task)

        handler_map = {
            MaintenanceTaskType.REBUILD_THUMBNAILS: self._task_rebuild_thumbnails,
            MaintenanceTaskType.REGENERATE_METADATA: self._task_regenerate_metadata,
            MaintenanceTaskType.RECOMPUTE_EMBEDDINGS: self._task_recompute_embeddings,
            MaintenanceTaskType.REBUILD_SEARCH_INDEX: self._task_rebuild_search_index,
            MaintenanceTaskType.REBUILD_KNOWLEDGE_GRAPH: self._task_rebuild_knowledge,
            MaintenanceTaskType.RECOMPUTE_HASHES: self._task_recompute_hashes,
            MaintenanceTaskType.REMOVE_ORPHAN_METADATA: self._task_remove_orphan_metadata,
            MaintenanceTaskType.REMOVE_ORPHAN_EMBEDDINGS: self._task_remove_orphan_embeddings,
            MaintenanceTaskType.REMOVE_ORPHAN_THUMBNAILS: self._task_remove_orphan_thumbnails,
            MaintenanceTaskType.REMOVE_ORPHAN_KNOWLEDGE_GRAPH: self._task_remove_orphan_knowledge,
            MaintenanceTaskType.REPAIR_BROKEN_CHARACTER_REFERENCES: self._task_repair_broken_character_refs,
            MaintenanceTaskType.REPAIR_BROKEN_SERIES_REFERENCES: self._task_repair_broken_series_refs,
            MaintenanceTaskType.REPAIR_COLLECTION_HIERARCHY: self._task_repair_collection_hierarchy,
            MaintenanceTaskType.REPAIR_REVIEW_REFERENCES: self._task_repair_review_refs,
            MaintenanceTaskType.REPAIR_ORGANIZER_HISTORY: self._task_repair_organizer_history,
            MaintenanceTaskType.REPAIR_RENAME_HISTORY: self._task_repair_rename_history,
            MaintenanceTaskType.RECALCULATE_LIBRARY_STATISTICS: self._task_recalculate_library_stats,
            MaintenanceTaskType.RECALCULATE_DUPLICATE_CACHE: self._task_recalculate_duplicate_cache,
            MaintenanceTaskType.RECALCULATE_TAG_STATISTICS: self._task_recalculate_tag_statistics,
            MaintenanceTaskType.REBUILD_DATASET_INDEXES: self._task_rebuild_dataset_indexes,
            MaintenanceTaskType.VALIDATE_EXPORT_MANIFESTS: self._task_validate_export_manifests,
            MaintenanceTaskType.REMOVE_TEMPORARY_FILES: self._task_remove_temporary_files,
            MaintenanceTaskType.CLEAN_STALE_CACHES: self._task_clean_stale_caches,
            MaintenanceTaskType.VACUUM_OPTIMIZE_DATABASE: self._task_vacuum_database,
            MaintenanceTaskType.COMPACT_INTERNAL_INDEXES: self._task_compact_indexes,
            MaintenanceTaskType.REMOVE_INVALID_QUEUE_ENTRIES: self._task_remove_invalid_queue_entries,
            MaintenanceTaskType.RETRY_INTERRUPTED_MAINTENANCE_JOBS: self._task_retry_interrupted_jobs,
        }
        return handler_map[task](dry_run=dry_run, job_id=job_id)

    def _preview_task(self, task: MaintenanceTaskType) -> MaintenanceResult:
        return MaintenanceResult(task=task, repaired_items=0, skipped_items=0, failed_items=0)

    def _task_rebuild_thumbnails(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        images = self.repository.scan_images()
        records = {row.image_id: row for row in self.repository.scan_thumbnails()}
        repaired = 0
        skipped = 0
        for image in images:
            path = Path(image.current_path or image.original_path)
            if not path.exists():
                skipped += 1
                continue
            record = records.get(image.id)
            file_missing = record is None or not Path(record.file_path).exists()
            if not file_missing:
                skipped += 1
                continue
            thumb_path = path.with_suffix(".webp")
            if not dry_run:
                thumb_path.write_bytes(b"thumb")
                self.repository.repair_thumbnails(image.id, str(thumb_path))
                image.thumbnail_exists = True
            repaired += 1
        if not dry_run:
            self.repository.session.commit()
        return MaintenanceResult(task=MaintenanceTaskType.REBUILD_THUMBNAILS, repaired_items=repaired, skipped_items=skipped)

    def _task_regenerate_metadata(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        images = self.repository.scan_images()
        metadata_ids = {row.image_id for row in self.repository.scan_metadata()}
        repaired = 0
        skipped = 0
        for image in images:
            path = Path(image.current_path or image.original_path)
            if not path.exists() or image.id in metadata_ids:
                skipped += 1
                continue
            if not dry_run:
                self.repository.repair_metadata(image.id)
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REGENERATE_METADATA, repaired_items=repaired, skipped_items=skipped)

    def _task_recompute_embeddings(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        images = self.repository.scan_images()
        embeddings = {row.image_id: row for row in self.repository.scan_embeddings()}
        repaired = 0
        skipped = 0
        failed = 0
        warnings: list[MaintenanceWarning] = []
        for image in images:
            path = Path(image.current_path or image.original_path)
            if not path.exists():
                skipped += 1
                continue
            row = embeddings.get(image.id)
            missing = row is None or not self._has_valid_embedding_artifact(row.vector_path)
            if not missing:
                skipped += 1
                continue
            if not dry_run:
                try:
                    result = self.embedding_service.process_embedding_job(
                        PipelineJob(source_path=str(path), queue_type=QueueType.EMBEDDING)
                    )
                except Exception as error:
                    failed += 1
                    warnings.append(MaintenanceWarning(MaintenanceTaskType.RECOMPUTE_EMBEDDINGS, f"Embedding regeneration failed for {path}: {error}"))
                    continue
                if result is None:
                    failed += 1
                    warnings.append(MaintenanceWarning(MaintenanceTaskType.RECOMPUTE_EMBEDDINGS, f"Embedding regeneration produced no artifact for {path}"))
                    continue
            repaired += 1
        if not dry_run:
            self.repository.session.commit()
        return MaintenanceResult(
            task=MaintenanceTaskType.RECOMPUTE_EMBEDDINGS,
            repaired_items=repaired,
            skipped_items=skipped,
            failed_items=failed,
            warnings=warnings,
        )

    def _task_rebuild_search_index(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        images = self.repository.scan_images()
        metadata_ids = {row.image_id for row in self.repository.scan_metadata()}
        embedding_ids = {row.image_id for row in self.repository.scan_embeddings()}
        repaired = 0
        skipped = 0
        for image in images:
            if image.id not in metadata_ids:
                skipped += 1
                continue
            if image.id in embedding_ids:
                skipped += 1
                continue
            if not dry_run:
                try:
                    result = self.embedding_service.process_embedding_job(
                        PipelineJob(
                            source_path=str(image.current_path or image.original_path),
                            queue_type=QueueType.EMBEDDING,
                        )
                    )
                except Exception:
                    skipped += 1
                    continue
                if result is None:
                    skipped += 1
                    continue
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REBUILD_SEARCH_INDEX, repaired_items=repaired, skipped_items=skipped)

    def _task_rebuild_knowledge(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        if dry_run:
            return MaintenanceResult(task=MaintenanceTaskType.REBUILD_KNOWLEDGE_GRAPH, repaired_items=1)
        self.repository.repair_knowledge_graph()
        return MaintenanceResult(task=MaintenanceTaskType.REBUILD_KNOWLEDGE_GRAPH, repaired_items=1)

    def _task_recompute_hashes(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        repaired = 0
        skipped = 0
        hash_ids = {row.image_id for row in self.repository.scan_hashes()}
        for image in self.repository.scan_images():
            if image.id in hash_ids:
                skipped += 1
                continue
            if not dry_run:
                source = Path(image.current_path or image.original_path)
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                self.repository.repair_hashes(image.id, digest)
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.RECOMPUTE_HASHES, repaired_items=repaired, skipped_items=skipped)

    @staticmethod
    def _has_valid_embedding_artifact(vector_path: str) -> bool:
        try:
            dimension, _, _ = EmbeddingRepository._read_artifact_metadata(vector_path)
        except ValueError:
            return False
        return dimension is not None

    def _task_remove_orphan_metadata(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        image_ids = {img.id for img in self.repository.scan_images()}
        repaired = 0
        for row in self.repository.scan_metadata():
            if row.image_id in image_ids:
                continue
            if not dry_run:
                self._append_rollback_record(
                    job_id,
                    MaintenanceRollbackRecord(
                        task=MaintenanceTaskType.REMOVE_ORPHAN_METADATA,
                        data={"image_id": row.image_id, "mime_type": row.mime_type, "exif_data": row.exif_data},
                    ),
                )
                self.repository.metadata_repository.delete_metadata_record(row)
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REMOVE_ORPHAN_METADATA, repaired_items=repaired)

    def _task_remove_orphan_embeddings(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        image_ids = {img.id for img in self.repository.scan_images()}
        repaired = 0
        for row in self.repository.scan_embeddings():
            if row.image_id in image_ids:
                continue
            if not dry_run:
                self._append_rollback_record(
                    job_id,
                    MaintenanceRollbackRecord(
                        task=MaintenanceTaskType.REMOVE_ORPHAN_EMBEDDINGS,
                        data={
                            "id": row.id,
                            "uuid": row.uuid,
                            "created_at": row.created_at,
                            "updated_at": row.updated_at,
                            "image_id": row.image_id,
                            "vector_path": row.vector_path,
                            "model_name": row.model_name,
                            "model_version": row.model_version,
                            "image_uuid": row.image_uuid,
                            "dimension": row.dimension,
                            "dtype": row.dtype,
                            "storage_path": row.storage_path,
                            "checksum": row.checksum,
                            "version": row.version,
                        },
                    ),
                )
                self.repository.embedding_repository.delete_embedding_record(row)
                self.repository.session.commit()
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REMOVE_ORPHAN_EMBEDDINGS, repaired_items=repaired)

    def _task_remove_orphan_thumbnails(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        image_ids = {img.id for img in self.repository.scan_images()}
        repaired = 0
        for row in self.repository.scan_thumbnails():
            if row.image_id in image_ids:
                continue
            if not dry_run:
                self._append_rollback_record(
                    job_id,
                    MaintenanceRollbackRecord(
                        task=MaintenanceTaskType.REMOVE_ORPHAN_THUMBNAILS,
                        data={
                            "image_id": row.image_id,
                            "size": row.size,
                            "format": row.format,
                            "file_path": row.file_path,
                            "file_size_bytes": row.file_size_bytes,
                            "cache_key": row.cache_key,
                            "thumb_width": row.thumb_width,
                            "thumb_height": row.thumb_height,
                        },
                    ),
                )
                self.repository.thumbnail_repository.delete_thumbnail_record(row)
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REMOVE_ORPHAN_THUMBNAILS, repaired_items=repaired)

    def _task_remove_orphan_knowledge(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        images = self.repository.scan_images()
        knowledge = self.repository.scan_knowledge()
        if images or not knowledge:
            return MaintenanceResult(task=MaintenanceTaskType.REMOVE_ORPHAN_KNOWLEDGE_GRAPH, skipped_items=1)
        repaired = len(knowledge)
        if not dry_run:
            for row in knowledge:
                self.repository.session.delete(row)
            self.repository.session.commit()
        return MaintenanceResult(task=MaintenanceTaskType.REMOVE_ORPHAN_KNOWLEDGE_GRAPH, repaired_items=repaired)

    def _task_repair_broken_character_refs(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        image_ids = {img.id for img in self.repository.scan_images()}
        character_ids = {row.id for row in self.repository.scan_characters()}
        repaired = 0
        for image in self.repository.scan_images():
            filtered = [char for char in image.characters if char.id in character_ids]
            if len(filtered) == len(image.characters):
                continue
            if not dry_run:
                image.characters = filtered
                self.repository.session.commit()
            repaired += 1
        # Remove entries whose image_id no longer exists by scanning association through ORM side effects.
        for orphan_id in sorted(set(image_ids)):
            _ = orphan_id
        return MaintenanceResult(task=MaintenanceTaskType.REPAIR_BROKEN_CHARACTER_REFERENCES, repaired_items=repaired)

    def _task_repair_broken_series_refs(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        series_ids = {row.id for row in self.repository.scan_series()}
        repaired = 0
        for image in self.repository.scan_images():
            if image.series_id is None or image.series_id in series_ids:
                continue
            if not dry_run:
                image.series_id = None
                self.repository.session.commit()
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REPAIR_BROKEN_SERIES_REFERENCES, repaired_items=repaired)

    def _task_repair_collection_hierarchy(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        rows = self.repository.scan_collections()
        by_id = {row.collection_id: row for row in rows}
        repaired = 0
        for row in rows:
            if row.parent_id is not None and row.parent_id not in by_id:
                if not dry_run:
                    self.repository.collection_repository.clear_parent(row.collection_id)
                repaired += 1

            visited: set[int] = set()
            current = row
            cycle_found = False
            while current.parent_id is not None:
                if current.parent_id in visited:
                    cycle_found = True
                    break
                visited.add(current.parent_id)
                nxt = by_id.get(current.parent_id)
                if nxt is None:
                    break
                current = nxt
            if cycle_found:
                if not dry_run:
                    self.repository.collection_repository.clear_parent(row.collection_id)
                repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REPAIR_COLLECTION_HIERARCHY, repaired_items=repaired)

    def _task_repair_review_refs(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        image_ids = {img.id for img in self.repository.scan_images()}
        repaired = 0
        for row in self.repository.scan_reviews():
            if row.image_id in image_ids:
                continue
            if not dry_run:
                self.repository.session.delete(row)
                self.repository.session.commit()
            repaired += 1
        stale_queue = [item for item in self.repository.review_repository.list_review_items() if item.image_id not in image_ids]
        if not dry_run:
            self.repository.review_repository.delete_review_items([item.review_id for item in stale_queue])
        repaired += len(stale_queue)
        return MaintenanceResult(task=MaintenanceTaskType.REPAIR_REVIEW_REFERENCES, repaired_items=repaired)

    def _task_repair_organizer_history(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        repaired = 0
        image_ids = {img.id for img in self.repository.scan_images()}
        for row in self.repository.scan_transactions():
            op = row.operation.lower()
            if op not in {"organize", "move"}:
                continue
            broken = (row.image_id is not None and row.image_id not in image_ids) or (row.new_path is not None and not Path(row.new_path).exists())
            if not broken:
                continue
            if not dry_run:
                row.status = "failed"
                self.repository.session.commit()
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REPAIR_ORGANIZER_HISTORY, repaired_items=repaired)

    def _task_repair_rename_history(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        repaired = 0
        image_ids = {img.id for img in self.repository.scan_images()}
        for row in self.repository.scan_transactions():
            if row.operation.lower() != "rename":
                continue
            broken = (row.image_id is not None and row.image_id not in image_ids) or (row.new_path is not None and not Path(row.new_path).exists())
            if not broken:
                continue
            if not dry_run:
                row.status = "failed"
                self.repository.session.commit()
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.REPAIR_RENAME_HISTORY, repaired_items=repaired)

    def _task_recalculate_library_stats(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        if dry_run:
            return MaintenanceResult(task=MaintenanceTaskType.RECALCULATE_LIBRARY_STATISTICS, repaired_items=1)
        payload = self.repository.repair_statistics()
        return MaintenanceResult(task=MaintenanceTaskType.RECALCULATE_LIBRARY_STATISTICS, repaired_items=payload["repaired"], skipped_items=max(0, payload["images"] - payload["repaired"]))

    def _task_recalculate_duplicate_cache(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        duplicates = self.repository.duplicate_repository.list_all_duplicates()
        repaired = 0
        for row in duplicates:
            if row.overall_score >= 0.7 and row.status != "pending":
                if not dry_run:
                    row.status = "pending"
                repaired += 1
        if not dry_run:
            self.repository.session.commit()
        return MaintenanceResult(task=MaintenanceTaskType.RECALCULATE_DUPLICATE_CACHE, repaired_items=repaired, skipped_items=max(0, len(duplicates) - repaired))

    def _task_recalculate_tag_statistics(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        tags = self.repository.scan_tags()
        orphan = [row for row in tags if len(row.images) == 0]
        repaired = 0
        if not dry_run:
            for row in orphan:
                self.repository.session.delete(row)
                repaired += 1
            self.repository.session.commit()
        else:
            repaired = len(orphan)
        return MaintenanceResult(task=MaintenanceTaskType.RECALCULATE_TAG_STATISTICS, repaired_items=repaired, skipped_items=max(0, len(tags) - repaired))

    def _task_rebuild_dataset_indexes(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        repaired = 0
        skipped = 0
        image_uuids = {img.uuid for img in self.repository.scan_images()}
        for record in self.repository.scan_dataset():
            if record.image_uuid not in image_uuids:
                if not dry_run:
                    self.repository.dataset_repository.delete_dataset_record(record.uuid)
                repaired += 1
            else:
                skipped += 1
        return MaintenanceResult(task=MaintenanceTaskType.REBUILD_DATASET_INDEXES, repaired_items=repaired, skipped_items=skipped)

    def _task_validate_export_manifests(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        payload = self.repository.scan_exports()
        manifests = payload["manifests"]
        valid_formats = set(payload["formats"])
        image_ids = {img.id for img in self.repository.scan_images()}

        repaired = 0
        skipped = 0
        for key, manifest in list(manifests.items()):
            fmt, image_id = key
            invalid = fmt not in valid_formats or image_id not in image_ids or not isinstance(manifest, dict)
            if invalid:
                if not dry_run:
                    self.repository.export_repository.clear_export_manifest(format_type=fmt, image_id=image_id)
                repaired += 1
                continue
            path_text = manifest.get("file_path") if isinstance(manifest, dict) else None
            if path_text and not Path(path_text).exists():
                if not dry_run:
                    self.repository.export_repository.clear_export_manifest(format_type=fmt, image_id=image_id)
                repaired += 1
            else:
                skipped += 1
        return MaintenanceResult(task=MaintenanceTaskType.VALIDATE_EXPORT_MANIFESTS, repaired_items=repaired, skipped_items=skipped)

    def _task_remove_temporary_files(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        workspace = Path.cwd()
        candidates = sorted([p for p in workspace.rglob("*.tmp") if p.is_file()] + [p for p in workspace.rglob("*.temp") if p.is_file()])
        if dry_run:
            return MaintenanceResult(task=MaintenanceTaskType.REMOVE_TEMPORARY_FILES, repaired_items=len(candidates))
        removed = self.repository.cleanup()
        return MaintenanceResult(task=MaintenanceTaskType.REMOVE_TEMPORARY_FILES, repaired_items=removed)

    def _task_clean_stale_caches(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        cache_root = Path.cwd() / "cache"
        if not cache_root.exists():
            return MaintenanceResult(task=MaintenanceTaskType.CLEAN_STALE_CACHES, skipped_items=1)
        stale = sorted([p for p in cache_root.rglob("*.stale") if p.is_file()])
        if dry_run:
            return MaintenanceResult(task=MaintenanceTaskType.CLEAN_STALE_CACHES, repaired_items=len(stale))
        removed = 0
        for item in stale:
            item.unlink(missing_ok=True)
            removed += 1
        return MaintenanceResult(task=MaintenanceTaskType.CLEAN_STALE_CACHES, repaired_items=removed)

    def _task_vacuum_database(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        if dry_run:
            return MaintenanceResult(task=MaintenanceTaskType.VACUUM_OPTIMIZE_DATABASE, repaired_items=1)
        self.repository.repair_database()
        return MaintenanceResult(task=MaintenanceTaskType.VACUUM_OPTIMIZE_DATABASE, repaired_items=1)

    def _task_compact_indexes(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        if dry_run:
            return MaintenanceResult(task=MaintenanceTaskType.COMPACT_INTERNAL_INDEXES, repaired_items=1)
        self.repository.repair_database()
        return MaintenanceResult(task=MaintenanceTaskType.COMPACT_INTERNAL_INDEXES, repaired_items=1)

    def _task_remove_invalid_queue_entries(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        repaired = self.repository.repair_queue() if not dry_run else len(self.repository.scan_jobs())
        return MaintenanceResult(task=MaintenanceTaskType.REMOVE_INVALID_QUEUE_ENTRIES, repaired_items=repaired)

    def _task_retry_interrupted_jobs(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        repaired = 0
        for row in self.repository.scan_jobs():
            if row.status.strip().lower() != "running":
                continue
            if not dry_run:
                row.status = "pending"
                row.progress = 0
                row.started_at = None
                row.finished_at = None
                self.repository.session.commit()
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.RETRY_INTERRUPTED_MAINTENANCE_JOBS, repaired_items=repaired)

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
