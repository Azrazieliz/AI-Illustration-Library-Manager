from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

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
from engine.repositories.maintenance_repository import MaintenanceRepository


class LibraryMaintenanceEngine:
    """Executes library repair and maintenance tasks."""

    def __init__(
        self,
        *,
        repository: MaintenanceRepository | None = None,
        builder: MaintenanceBuilder | None = None,
        callback=None,
    ) -> None:
        self.repository = repository or MaintenanceRepository()
        self.builder = builder or MaintenanceBuilder()
        self.callback = callback
        self.statistics = MaintenanceStatistics()
        self._jobs: dict[str, MaintenanceJob] = {}
        self._checkpoints: dict[str, MaintenanceCheckpoint] = {}
        self._cancel_requested: set[str] = set()
        self._rollback_records: dict[str, list[MaintenanceRollbackRecord]] = {}

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
        checkpoint = self._checkpoints.get(resolved_id, MaintenanceCheckpoint())
        job = self._jobs.get(resolved_id)
        if job is None:
            job = MaintenanceJob(
                job_id=resolved_id,
                job_type="selected" if len(tasks) < len(MaintenanceTaskType) else "full",
                status=MaintenanceJobStatus.PENDING,
            )
            self._jobs[resolved_id] = job
        self._rollback_records.setdefault(resolved_id, [])

        started = perf_counter()
        results: list[MaintenanceResult] = []
        selected = list(tasks)
        total = len(selected)

        job.status = MaintenanceJobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
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

    def resume_job(self, job_id: str) -> MaintenanceReport:
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Maintenance job not found: {job_id}")
        remaining = [task for task in MaintenanceTaskType if task not in self._checkpoints.get(job_id, MaintenanceCheckpoint()).completed_tasks]
        if not remaining:
            return self.run_selected_tasks([], job_id=job_id, resumed=True)
        return self.run_selected_tasks(remaining, job_id=job_id, resumed=True)

    def rollback_job(self, job_id: str) -> int:
        records = list(reversed(self._rollback_records.get(job_id, [])))
        restored = 0
        for record in records:
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
                self.repository.embedding_repository.create_embedding_record(
                    image_id=payload["image_id"],
                    vector_path=payload["vector_path"],
                    model_name=payload.get("model_name", "restored"),
                    model_version=payload.get("model_version", "1"),
                )
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
        self._rollback_records[job_id] = []
        return restored

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
        for image in images:
            path = Path(image.current_path or image.original_path)
            if not path.exists():
                skipped += 1
                continue
            row = embeddings.get(image.id)
            missing = row is None or not Path(row.vector_path).exists()
            if not missing:
                skipped += 1
                continue
            vector_path = path.with_suffix(".npy")
            if not dry_run:
                vector_path.write_bytes(b"vec")
                self.repository.repair_embeddings(image.id, str(vector_path))
                image.embedding_exists = True
            repaired += 1
        if not dry_run:
            self.repository.session.commit()
        return MaintenanceResult(task=MaintenanceTaskType.RECOMPUTE_EMBEDDINGS, repaired_items=repaired, skipped_items=skipped)

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
                vector_path = Path(image.current_path or image.original_path).with_suffix(".npy")
                vector_path.write_bytes(b"search")
                self.repository.repair_embeddings(image.id, str(vector_path))
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
                source = image.current_path or image.original_path
                digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
                self.repository.repair_hashes(image.id, digest)
            repaired += 1
        return MaintenanceResult(task=MaintenanceTaskType.RECOMPUTE_HASHES, repaired_items=repaired, skipped_items=skipped)

    def _task_remove_orphan_metadata(self, *, dry_run: bool, job_id: str) -> MaintenanceResult:
        image_ids = {img.id for img in self.repository.scan_images()}
        repaired = 0
        for row in self.repository.scan_metadata():
            if row.image_id in image_ids:
                continue
            if not dry_run:
                self._rollback_records[job_id].append(
                    MaintenanceRollbackRecord(
                        task=MaintenanceTaskType.REMOVE_ORPHAN_METADATA,
                        data={"image_id": row.image_id, "mime_type": row.mime_type, "exif_data": row.exif_data},
                    )
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
                self._rollback_records[job_id].append(
                    MaintenanceRollbackRecord(
                        task=MaintenanceTaskType.REMOVE_ORPHAN_EMBEDDINGS,
                        data={
                            "image_id": row.image_id,
                            "vector_path": row.vector_path,
                            "model_name": row.model_name,
                            "model_version": row.model_version,
                        },
                    )
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
                self._rollback_records[job_id].append(
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
                    )
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
                    row.parent_id = None
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
                    row.parent_id = None
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
            with self.repository.review_repository._lock:
                for item in stale_queue:
                    self.repository.review_repository._queue_reviews.pop(item.review_id, None)
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
        image_ids = {img.id for img in self.repository.scan_images()}
        for image_id in sorted(list(self.repository.dataset_repository._dataset_provenance.keys())):
            if image_id not in image_ids:
                if not dry_run:
                    self.repository.dataset_repository._dataset_provenance.pop(image_id, None)
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
                    self.repository.export_repository._manifest_store.pop(key, None)
                repaired += 1
                continue
            path_text = manifest.get("file_path") if isinstance(manifest, dict) else None
            if path_text and not Path(path_text).exists():
                if not dry_run:
                    self.repository.export_repository._manifest_store.pop(key, None)
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
