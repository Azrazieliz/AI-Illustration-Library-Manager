from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from engine.library_integrity.integrity_builder import IntegrityBuilder
from engine.library_integrity.integrity_models import (
    IntegrityCheckName,
    IntegrityCheckpoint,
    IntegrityIssue,
    IntegrityProgress,
    IntegrityReport,
    IntegritySeverity,
)
from engine.library_integrity.integrity_statistics import IntegrityStatistics
from engine.repositories.integrity_repository import IntegrityRepository

_ILLEGAL_FILENAME_CHARS = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


class LibraryIntegrityEngine:
    """Runs read-only consistency checks across the full illustration library."""

    def __init__(
        self,
        *,
        repository: IntegrityRepository | None = None,
        builder: IntegrityBuilder | None = None,
        callback: Callable[[object], None] | None = None,
    ) -> None:
        self.repository = repository or IntegrityRepository()
        self.builder = builder or IntegrityBuilder()
        self.callback = callback
        self.statistics = IntegrityStatistics()
        self._cancel_requested: set[str] = set()
        self._checkpoints: dict[str, IntegrityCheckpoint] = {}

    def run_full_scan(self, *, scan_id: str | None = None, checkpoint: IntegrityCheckpoint | None = None, resumed: bool = False) -> IntegrityReport:
        return self._run(mode="full", scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)

    def run_quick_scan(self, *, scan_id: str | None = None, checkpoint: IntegrityCheckpoint | None = None, resumed: bool = False) -> IntegrityReport:
        return self._run(mode="quick", scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)

    def run_database_scan(self, *, scan_id: str | None = None, checkpoint: IntegrityCheckpoint | None = None, resumed: bool = False) -> IntegrityReport:
        return self._run(mode="database", scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)

    def run_filesystem_scan(self, *, scan_id: str | None = None, checkpoint: IntegrityCheckpoint | None = None, resumed: bool = False) -> IntegrityReport:
        return self._run(mode="filesystem", scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)

    def request_cancel(self, scan_id: str) -> None:
        self._cancel_requested.add(scan_id)

    def checkpoint_for(self, scan_id: str) -> IntegrityCheckpoint:
        existing = self._checkpoints.get(scan_id)
        if existing is None:
            return IntegrityCheckpoint()
        return IntegrityCheckpoint(completed_checks=set(existing.completed_checks))

    def _run(self, *, mode: str, scan_id: str | None, checkpoint: IntegrityCheckpoint | None, resumed: bool) -> IntegrityReport:
        resolved_scan_id = scan_id or str(uuid4())
        resolved_checkpoint = checkpoint or IntegrityCheckpoint()

        context = self._scan_context()
        checks = self._checks_for_mode(mode)

        check_results = []
        cancelled = False
        started = perf_counter()

        completed = len([name for name, _ in checks if resolved_checkpoint.contains(name)])
        total = len(checks)

        for check_name, handler in checks:
            if resolved_checkpoint.contains(check_name):
                continue

            if resolved_scan_id in self._cancel_requested:
                cancelled = True
                break

            self._emit(
                IntegrityProgress(
                    scan_id=resolved_scan_id,
                    completed_checks=completed,
                    total_checks=total,
                    current_check=check_name,
                    cancelled=False,
                )
            )

            check_started = perf_counter()
            issues = handler(context)
            duration = perf_counter() - check_started
            check_results.append(
                self.builder.build_check_result(
                    check_name=check_name,
                    issues=issues,
                    duration_seconds=duration,
                )
            )
            resolved_checkpoint.add(check_name)
            completed += 1

        elapsed = perf_counter() - started
        report = self.builder.build_report(
            check_results=check_results,
            execution_time_seconds=elapsed,
            cancelled=cancelled,
            resumed=resumed,
        )

        self.statistics.record_scan(
            duration_seconds=elapsed,
            checks_performed=report.summary.checks_performed,
            warnings=report.summary.warnings,
            errors=report.summary.errors,
            critical_errors=report.summary.critical_errors,
        )
        self._checkpoints[resolved_scan_id] = resolved_checkpoint

        self._emit(
            IntegrityProgress(
                scan_id=resolved_scan_id,
                completed_checks=completed,
                total_checks=total,
                current_check=None,
                cancelled=cancelled,
            )
        )

        if cancelled:
            self._cancel_requested.discard(resolved_scan_id)

        return report

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)

    def _checks_for_mode(self, mode: str) -> list[tuple[IntegrityCheckName, Callable[[dict[str, Any]], list[IntegrityIssue]]]]:
        all_checks: list[tuple[IntegrityCheckName, Callable[[dict[str, Any]], list[IntegrityIssue]]]] = [
            (IntegrityCheckName.MISSING_IMAGE_FILES, self._check_missing_image_files),
            (IntegrityCheckName.MISSING_THUMBNAILS, self._check_missing_thumbnails),
            (IntegrityCheckName.MISSING_METADATA, self._check_missing_metadata),
            (IntegrityCheckName.MISSING_EMBEDDINGS, self._check_missing_embeddings),
            (IntegrityCheckName.MISSING_KNOWLEDGE_GRAPH_ENTRIES, self._check_missing_knowledge_entries),
            (IntegrityCheckName.MISSING_SEARCH_INDEX, self._check_missing_search_index),
            (IntegrityCheckName.MISSING_TAGS, self._check_missing_tags),
            (IntegrityCheckName.ORPHAN_METADATA, self._check_orphan_metadata),
            (IntegrityCheckName.ORPHAN_EMBEDDINGS, self._check_orphan_embeddings),
            (IntegrityCheckName.ORPHAN_THUMBNAILS, self._check_orphan_thumbnails),
            (IntegrityCheckName.ORPHAN_KNOWLEDGE_GRAPH_NODES, self._check_orphan_knowledge_nodes),
            (IntegrityCheckName.BROKEN_CHARACTER_REFERENCES, self._check_broken_character_references),
            (IntegrityCheckName.BROKEN_SERIES_REFERENCES, self._check_broken_series_references),
            (IntegrityCheckName.BROKEN_COLLECTION_REFERENCES, self._check_broken_collection_references),
            (IntegrityCheckName.BROKEN_REVIEW_REFERENCES, self._check_broken_review_references),
            (IntegrityCheckName.BROKEN_RENAME_HISTORY, self._check_broken_rename_history),
            (IntegrityCheckName.BROKEN_ORGANIZER_HISTORY, self._check_broken_organizer_history),
            (IntegrityCheckName.DUPLICATE_UUID_DETECTION, self._check_duplicate_uuids),
            (IntegrityCheckName.DUPLICATE_DATABASE_IDS, self._check_duplicate_database_ids),
            (IntegrityCheckName.INVALID_PATHS, self._check_invalid_paths),
            (IntegrityCheckName.CASE_COLLISION_DETECTION, self._check_case_collisions),
            (IntegrityCheckName.RESERVED_FILENAME_DETECTION, self._check_reserved_filenames),
            (IntegrityCheckName.FILENAME_VALIDATION, self._check_filename_validation),
            (IntegrityCheckName.DATABASE_CONSISTENCY, self._check_database_consistency),
            (IntegrityCheckName.PIPELINE_CONSISTENCY, self._check_pipeline_consistency),
            (IntegrityCheckName.COLLECTION_CONSISTENCY, self._check_collection_consistency),
            (IntegrityCheckName.RECOGNITION_CONSISTENCY, self._check_recognition_consistency),
            (IntegrityCheckName.STATISTICS_CONSISTENCY, self._check_statistics_consistency),
            (IntegrityCheckName.DATASET_CONSISTENCY, self._check_dataset_consistency),
            (IntegrityCheckName.EXPORT_CONSISTENCY, self._check_export_consistency),
        ]

        if mode == "full":
            return all_checks

        if mode == "quick":
            names = {
                IntegrityCheckName.MISSING_IMAGE_FILES,
                IntegrityCheckName.MISSING_THUMBNAILS,
                IntegrityCheckName.MISSING_METADATA,
                IntegrityCheckName.MISSING_EMBEDDINGS,
                IntegrityCheckName.MISSING_TAGS,
                IntegrityCheckName.INVALID_PATHS,
                IntegrityCheckName.FILENAME_VALIDATION,
                IntegrityCheckName.DATABASE_CONSISTENCY,
                IntegrityCheckName.PIPELINE_CONSISTENCY,
            }
            return [item for item in all_checks if item[0] in names]

        if mode == "database":
            names = {
                IntegrityCheckName.ORPHAN_METADATA,
                IntegrityCheckName.ORPHAN_EMBEDDINGS,
                IntegrityCheckName.BROKEN_CHARACTER_REFERENCES,
                IntegrityCheckName.BROKEN_SERIES_REFERENCES,
                IntegrityCheckName.BROKEN_COLLECTION_REFERENCES,
                IntegrityCheckName.BROKEN_REVIEW_REFERENCES,
                IntegrityCheckName.DUPLICATE_UUID_DETECTION,
                IntegrityCheckName.DUPLICATE_DATABASE_IDS,
                IntegrityCheckName.DATABASE_CONSISTENCY,
                IntegrityCheckName.COLLECTION_CONSISTENCY,
                IntegrityCheckName.RECOGNITION_CONSISTENCY,
                IntegrityCheckName.STATISTICS_CONSISTENCY,
            }
            return [item for item in all_checks if item[0] in names]

        if mode == "filesystem":
            names = {
                IntegrityCheckName.MISSING_IMAGE_FILES,
                IntegrityCheckName.MISSING_THUMBNAILS,
                IntegrityCheckName.MISSING_EMBEDDINGS,
                IntegrityCheckName.INVALID_PATHS,
                IntegrityCheckName.CASE_COLLISION_DETECTION,
                IntegrityCheckName.RESERVED_FILENAME_DETECTION,
                IntegrityCheckName.FILENAME_VALIDATION,
                IntegrityCheckName.DATASET_CONSISTENCY,
                IntegrityCheckName.EXPORT_CONSISTENCY,
            }
            return [item for item in all_checks if item[0] in names]

        return all_checks

    def _scan_context(self) -> dict[str, Any]:
        db = self.repository.scan_database()
        reviews_db, reviews_queue = self.repository.scan_reviews()
        return {
            "images": db["images"],
            "metadata": db["metadata"],
            "embeddings": db["embeddings"],
            "thumbnails": db["thumbnails"],
            "knowledge": db["knowledge"],
            "series": db["series"],
            "characters": db["characters"],
            "tags": db["tags"],
            "transactions": db["transactions"],
            "reviews_db": reviews_db,
            "reviews_queue": reviews_queue,
            "collections": self.repository.scan_collections(),
            "jobs": self.repository.scan_pipeline().jobs,
            "now": self.repository.scan_pipeline().now,
            "dataset": self.repository.scan_dataset(),
            "exports": self.repository.scan_exports(),
            "image_character_links": db["image_character_links"],
            "image_tag_links": db["image_tag_links"],
        }

    def _check_missing_image_files(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            path = self._image_path(image)
            if path is None or path.exists():
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem="filesystem",
                    description="Image record exists but source file is missing.",
                    image_id=image.id,
                    file_path=str(path),
                    suggested_repair="Restore file or remove stale image record.",
                )
            )
        return issues

    def _check_missing_thumbnails(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        thumbnail_by_image: dict[int, list[Any]] = {}
        for thumb in context["thumbnails"]:
            thumbnail_by_image.setdefault(thumb.image_id, []).append(thumb)

        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            path = self._image_path(image)
            if path is None or not path.exists():
                continue
            thumbs = thumbnail_by_image.get(image.id, [])
            if not thumbs:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="thumbnails",
                        description="Image exists but has no thumbnail record.",
                        image_id=image.id,
                        file_path=str(path),
                        suggested_repair="Regenerate thumbnail for this image.",
                    )
                )
                continue
            for thumb in thumbs:
                thumb_path = Path(thumb.file_path)
                if thumb_path.exists():
                    continue
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="thumbnails",
                        description="Thumbnail record exists but thumbnail file is missing.",
                        image_id=image.id,
                        file_path=str(thumb_path),
                        suggested_repair="Regenerate thumbnail and refresh thumbnail record.",
                    )
                )
        return issues

    def _check_missing_metadata(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        metadata_ids = {item.image_id for item in context["metadata"]}
        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            path = self._image_path(image)
            if path is None or not path.exists():
                continue
            if image.id in metadata_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="metadata",
                    description="Image exists but metadata is missing.",
                    image_id=image.id,
                    file_path=str(path),
                    suggested_repair="Re-run metadata extraction.",
                )
            )
        return issues

    def _check_missing_embeddings(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        embedding_ids = {item.image_id for item in context["embeddings"]}
        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            path = self._image_path(image)
            if path is None or not path.exists():
                continue
            if image.id in embedding_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="embeddings",
                    description="Image exists but embedding is missing.",
                    image_id=image.id,
                    file_path=str(path),
                    suggested_repair="Re-run embedding generation.",
                )
            )
        return issues

    def _check_missing_knowledge_entries(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        if context["images"] and not context["knowledge"]:
            return [
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="knowledge_graph",
                    description="Library has images but no knowledge graph snapshot exists.",
                    suggested_repair="Rebuild knowledge graph snapshot.",
                )
            ]
        return []

    def _check_missing_search_index(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        metadata_ids = {item.image_id for item in context["metadata"]}
        embedding_ids = {item.image_id for item in context["embeddings"]}
        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            path = self._image_path(image)
            if path is None or not path.exists():
                continue
            if image.id not in metadata_ids:
                continue
            if image.id in embedding_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="search",
                    description="Search index entry is missing for metadata-complete image.",
                    image_id=image.id,
                    file_path=str(path),
                    suggested_repair="Re-run search indexing for this image.",
                )
            )
        return issues

    def _check_missing_tags(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            path = self._image_path(image)
            if path is None or not path.exists():
                continue
            if image.tags:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.INFO,
                    subsystem="tagging",
                    description="Image has never been tagged.",
                    image_id=image.id,
                    file_path=str(path),
                    suggested_repair="Run tagging pipeline for this image.",
                )
            )
        return issues

    def _check_orphan_metadata(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {image.id for image in context["images"]}
        issues: list[IntegrityIssue] = []
        for record in context["metadata"]:
            if record.image_id in image_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem="metadata",
                    description="Metadata references a missing image.",
                    image_id=record.image_id,
                    suggested_repair="Delete orphan metadata record or restore image.",
                )
            )
        return issues

    def _check_orphan_embeddings(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {image.id for image in context["images"]}
        issues: list[IntegrityIssue] = []
        for record in context["embeddings"]:
            if record.image_id in image_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem="embeddings",
                    description="Embedding references a missing image.",
                    image_id=record.image_id,
                    file_path=record.vector_path,
                    suggested_repair="Delete orphan embedding or restore image.",
                )
            )
        return issues

    def _check_orphan_thumbnails(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {image.id for image in context["images"]}
        issues: list[IntegrityIssue] = []
        for record in context["thumbnails"]:
            if record.image_id in image_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem="thumbnails",
                    description="Thumbnail references a missing source image.",
                    image_id=record.image_id,
                    file_path=record.file_path,
                    suggested_repair="Delete orphan thumbnail and thumbnail record.",
                )
            )
        return issues

    def _check_orphan_knowledge_nodes(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        if context["knowledge"] and not context["images"]:
            return [
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="knowledge_graph",
                    description="Knowledge graph snapshot exists but no images remain in library.",
                    suggested_repair="Archive old knowledge snapshot.",
                )
            ]
        return []

    def _check_broken_character_references(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        character_ids = {item.id for item in context["characters"]}
        image_ids = {item.id for item in context["images"]}
        issues: list[IntegrityIssue] = []
        for row in context["image_character_links"]:
            image_id = int(row.image_id)
            character_id = int(row.character_id)
            if image_id not in image_ids or character_id not in character_ids:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="recognition",
                        description=f"Broken image-character reference (image_id={image_id}, character_id={character_id}).",
                        image_id=image_id,
                        suggested_repair="Remove broken relation or restore referenced entities.",
                    )
                )
        return issues

    def _check_broken_series_references(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        series_ids = {item.id for item in context["series"]}
        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            if image.series_id is None or image.series_id in series_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem="recognition",
                    description=f"Image references missing series id {image.series_id}.",
                    image_id=image.id,
                    suggested_repair="Clear series reference or recreate missing series entry.",
                )
            )
        return issues

    def _check_broken_collection_references(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {item.id for item in context["images"]}
        issues: list[IntegrityIssue] = []
        for collection in context["collections"]:
            for image_id in sorted(collection.image_ids):
                if image_id in image_ids:
                    continue
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="collections",
                        description=f"Collection {collection.collection_id} references missing image {image_id}.",
                        image_id=image_id,
                        suggested_repair="Remove stale image membership from collection.",
                    )
                )
        return issues

    def _check_broken_review_references(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {item.id for item in context["images"]}
        issues: list[IntegrityIssue] = []
        for review in context["reviews_db"]:
            if review.image_id in image_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem="review",
                    description=f"Review record {review.id} references missing image {review.image_id}.",
                    image_id=review.image_id,
                    suggested_repair="Delete orphan review record.",
                )
            )
        for review in context["reviews_queue"]:
            if review.image_id in image_ids:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="review",
                    description=f"Queued review {review.review_id} references missing image {review.image_id}.",
                    image_id=review.image_id,
                    file_path=str(review.source_path),
                    suggested_repair="Drop stale queued review item.",
                )
            )
        return issues

    def _check_broken_rename_history(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {item.id for item in context["images"]}
        issues: list[IntegrityIssue] = []
        for tx in context["transactions"]:
            if tx.operation.lower() != "rename":
                continue
            if tx.image_id is not None and tx.image_id not in image_ids:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="rename",
                        description=f"Rename transaction {tx.id} references missing image {tx.image_id}.",
                        image_id=tx.image_id,
                        suggested_repair="Remove stale rename transaction record.",
                    )
                )
            if tx.new_path and not Path(tx.new_path).exists():
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="rename",
                        description=f"Rename transaction {tx.id} points to missing destination path.",
                        file_path=tx.new_path,
                        suggested_repair="Reconcile rename transaction with current filesystem state.",
                    )
                )
        return issues

    def _check_broken_organizer_history(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {item.id for item in context["images"]}
        issues: list[IntegrityIssue] = []
        for tx in context["transactions"]:
            operation = tx.operation.lower()
            if operation not in {"organize", "move"}:
                continue
            if tx.image_id is not None and tx.image_id not in image_ids:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="organizer",
                        description=f"Organizer transaction {tx.id} references missing image {tx.image_id}.",
                        image_id=tx.image_id,
                        suggested_repair="Remove stale organizer transaction record.",
                    )
                )
            if tx.new_path and not Path(tx.new_path).exists():
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="organizer",
                        description=f"Organizer transaction {tx.id} points to missing destination path.",
                        file_path=tx.new_path,
                        suggested_repair="Re-run organizer for missing destination file.",
                    )
                )
        return issues

    def _check_duplicate_uuids(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        values: dict[str, list[str]] = {}
        entities = {
            "image": context["images"],
            "metadata": context["metadata"],
            "embedding": context["embeddings"],
            "thumbnail": context["thumbnails"],
            "knowledge": context["knowledge"],
            "series": context["series"],
            "character": context["characters"],
            "tag": context["tags"],
            "transaction": context["transactions"],
            "review": context["reviews_db"],
            "job": context["jobs"],
        }
        for label, rows in entities.items():
            for row in rows:
                values.setdefault(row.uuid, []).append(f"{label}:{row.id}")

        issues: list[IntegrityIssue] = []
        for uuid_value in sorted(values.keys()):
            refs = values[uuid_value]
            if len(refs) <= 1:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.CRITICAL,
                    subsystem="database",
                    description=f"Duplicate UUID detected: {uuid_value} ({', '.join(sorted(refs))}).",
                    suggested_repair="Regenerate colliding UUIDs and audit related records.",
                )
            )
        return issues

    def _check_duplicate_database_ids(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        entities = {
            "image": [item.id for item in context["images"]],
            "metadata": [item.id for item in context["metadata"]],
            "embedding": [item.id for item in context["embeddings"]],
            "thumbnail": [item.id for item in context["thumbnails"]],
            "knowledge": [item.id for item in context["knowledge"]],
            "series": [item.id for item in context["series"]],
            "character": [item.id for item in context["characters"]],
            "tag": [item.id for item in context["tags"]],
            "transaction": [item.id for item in context["transactions"]],
            "review": [item.id for item in context["reviews_db"]],
            "job": [item.id for item in context["jobs"]],
            "collection": [item.collection_id for item in context["collections"]],
            "queue_review": [item.review_id for item in context["reviews_queue"]],
        }
        for label, ids in entities.items():
            seen: set[int] = set()
            duplicates: set[int] = set()
            for value in ids:
                if value in seen:
                    duplicates.add(value)
                seen.add(value)
            for duplicate in sorted(duplicates):
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.CRITICAL,
                        subsystem="database",
                        description=f"Duplicate database id detected for {label}: {duplicate}.",
                        suggested_repair="Investigate id allocation or import conflict.",
                    )
                )
        return issues

    def _check_invalid_paths(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []

        for image in context["images"]:
            candidate = image.current_path or image.original_path
            issues.extend(self._validate_path_text(candidate, subsystem="filesystem", image_id=image.id))

        for thumbnail in context["thumbnails"]:
            issues.extend(self._validate_path_text(thumbnail.file_path, subsystem="thumbnails", image_id=thumbnail.image_id))

        for embedding in context["embeddings"]:
            issues.extend(self._validate_path_text(embedding.vector_path, subsystem="embeddings", image_id=embedding.image_id))

        return issues

    def _check_case_collisions(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        by_normalized: dict[str, list[tuple[int, str]]] = {}
        for image in context["images"]:
            path = image.current_path or image.original_path
            normalized = str(Path(path)).lower()
            by_normalized.setdefault(normalized, []).append((image.id, path))

        issues: list[IntegrityIssue] = []
        for normalized in sorted(by_normalized.keys()):
            refs = by_normalized[normalized]
            unique_paths = {value for _, value in refs}
            if len(unique_paths) <= 1:
                continue
            ids = ", ".join(str(image_id) for image_id, _ in sorted(refs))
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="filesystem",
                    description=f"Case-collision detected across image paths (image_ids={ids}).",
                    suggested_repair="Normalize path casing to a single canonical style.",
                )
            )
        return issues

    def _check_reserved_filenames(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            path = self._image_path(image)
            if path is None:
                continue
            stem_upper = path.stem.strip().upper()
            if stem_upper not in _RESERVED_WINDOWS_NAMES:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem="filesystem",
                    description=f"Reserved filename detected: {path.name}.",
                    image_id=image.id,
                    file_path=str(path),
                    suggested_repair="Rename file to a non-reserved name.",
                )
            )
        return issues

    def _check_filename_validation(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        for image in context["images"]:
            path = self._image_path(image)
            if path is None:
                continue
            filename = path.name
            if _ILLEGAL_FILENAME_CHARS.search(filename):
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="filesystem",
                        description=f"Filename has illegal characters: {filename}.",
                        image_id=image.id,
                        file_path=str(path),
                        suggested_repair="Rename file to remove illegal characters.",
                    )
                )
            if filename.endswith(" ") or filename.endswith("."):
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="filesystem",
                        description=f"Filename has trailing space or period: {filename}.",
                        image_id=image.id,
                        file_path=str(path),
                        suggested_repair="Trim trailing spaces/periods in filename.",
                    )
                )
            if len(filename) > 255:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="filesystem",
                        description=f"Filename exceeds portable length limit: {len(filename)} characters.",
                        image_id=image.id,
                        file_path=str(path),
                        suggested_repair="Shorten filename for cross-platform compatibility.",
                    )
                )
        return issues

    def _check_database_consistency(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []

        broken_count = 0
        broken_count += len(self._check_orphan_metadata(context))
        broken_count += len(self._check_orphan_embeddings(context))
        broken_count += len(self._check_orphan_thumbnails(context))
        broken_count += len(self._check_broken_character_references(context))
        broken_count += len(self._check_broken_series_references(context))
        broken_count += len(self._check_broken_review_references(context))

        tag_ids = {item.id for item in context["tags"]}
        image_ids = {item.id for item in context["images"]}
        for row in context["image_tag_links"]:
            if int(row.image_id) not in image_ids or int(row.tag_id) not in tag_ids:
                broken_count += 1

        if broken_count > 0:
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.CRITICAL,
                    subsystem="database",
                    description=f"Database consistency check found {broken_count} broken relationships/references.",
                    suggested_repair="Run targeted migration and cleanup for broken references.",
                )
            )
        return issues

    def _check_pipeline_consistency(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        now = context["now"]
        valid_statuses = {"pending", "running", "finished", "cancelled", "failed"}

        for job in context["jobs"]:
            status = job.status.strip().lower()
            if status not in valid_statuses:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="pipeline",
                        description=f"Job {job.id} has invalid status '{job.status}'.",
                        suggested_repair="Normalize job status to known lifecycle state.",
                    )
                )
            if job.progress < 0 or job.progress > 100:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="pipeline",
                        description=f"Job {job.id} has invalid progress value {job.progress}.",
                        suggested_repair="Clamp progress to [0,100] and audit job updater.",
                    )
                )
            if status == "running" and job.started_at is not None:
                age = now - job.started_at
                if age > timedelta(hours=1):
                    issues.append(
                        IntegrityIssue(
                            severity=IntegritySeverity.WARNING,
                            subsystem="pipeline",
                            description=f"Job {job.id} appears stuck in running state.",
                            suggested_repair="Inspect worker logs and mark or restart stuck job.",
                        )
                    )
            if status == "pending" and job.finished_at is not None:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="pipeline",
                        description=f"Job {job.id} is pending but has finished_at set.",
                        suggested_repair="Correct inconsistent job timestamps/state.",
                    )
                )
        return issues

    def _check_collection_consistency(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        collections = context["collections"]
        by_id = {item.collection_id: item for item in collections}
        issues: list[IntegrityIssue] = []

        for collection in collections:
            if collection.parent_id is None:
                continue
            if collection.parent_id in by_id:
                continue
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem="collections",
                    description=f"Collection {collection.collection_id} has missing parent {collection.parent_id}.",
                    suggested_repair="Reassign parent or remove broken parent reference.",
                )
            )

        for collection in collections:
            seen: set[int] = set()
            current = collection
            while current.parent_id is not None:
                parent_id = current.parent_id
                if parent_id in seen:
                    issues.append(
                        IntegrityIssue(
                            severity=IntegritySeverity.CRITICAL,
                            subsystem="collections",
                            description=f"Circular collection hierarchy detected at collection {collection.collection_id}.",
                            suggested_repair="Break cycle in collection parent relationships.",
                        )
                    )
                    break
                seen.add(parent_id)
                parent = by_id.get(parent_id)
                if parent is None:
                    break
                current = parent
        return issues

    def _check_recognition_consistency(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        series_ids = {item.id for item in context["series"]}

        for character in context["characters"]:
            if character.series_id is not None and character.series_id not in series_ids:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="recognition",
                        description=f"Character {character.id} references missing series {character.series_id}.",
                        suggested_repair="Reassign character series or restore missing series.",
                    )
                )
            if self._has_invalid_aliases(character.aliases):
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="recognition",
                        description=f"Character {character.id} has invalid alias formatting.",
                        suggested_repair="Normalize alias list and remove empty aliases.",
                    )
                )

        for series in context["series"]:
            if self._has_invalid_aliases(series.aliases):
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="recognition",
                        description=f"Series {series.id} has invalid alias formatting.",
                        suggested_repair="Normalize series alias list.",
                    )
                )
        return issues

    def _check_statistics_consistency(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        thumbnail_image_ids = {item.image_id for item in context["thumbnails"]}
        embedding_image_ids = {item.image_id for item in context["embeddings"]}

        thumbnail_mismatch = 0
        embedding_mismatch = 0
        for image in context["images"]:
            expected_thumbnail = image.id in thumbnail_image_ids
            expected_embedding = image.id in embedding_image_ids
            if bool(image.thumbnail_exists) != expected_thumbnail:
                thumbnail_mismatch += 1
            if bool(image.embedding_exists) != expected_embedding:
                embedding_mismatch += 1

        if thumbnail_mismatch > 0:
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="statistics",
                    description=f"Thumbnail flag mismatch detected for {thumbnail_mismatch} images.",
                    suggested_repair="Recalculate thumbnail_exists flags from thumbnail table.",
                )
            )
        if embedding_mismatch > 0:
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem="statistics",
                    description=f"Embedding flag mismatch detected for {embedding_mismatch} images.",
                    suggested_repair="Recalculate embedding_exists flags from embedding table.",
                )
            )
        return issues

    def _check_dataset_consistency(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {item.id for item in context["images"]}
        provenance = context["dataset"]
        issues: list[IntegrityIssue] = []

        for image_id in sorted(provenance.keys()):
            if image_id not in image_ids:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="dataset",
                        description=f"Dataset provenance references missing image {image_id}.",
                        image_id=image_id,
                        suggested_repair="Remove orphan dataset provenance entry.",
                    )
                )
            for source_path in sorted(provenance[image_id]):
                if Path(source_path).exists():
                    continue
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="dataset",
                        description=f"Dataset provenance path is missing on disk for image {image_id}.",
                        image_id=image_id,
                        file_path=source_path,
                        suggested_repair="Regenerate dataset export from current source image.",
                    )
                )
        return issues

    def _check_export_consistency(self, context: dict[str, Any]) -> list[IntegrityIssue]:
        image_ids = {item.id for item in context["images"]}
        payload = context["exports"]
        manifests = payload["manifests"]
        known_formats = set(payload["known_formats"])

        issues: list[IntegrityIssue] = []
        for (format_name, image_id), manifest in sorted(manifests.items(), key=lambda item: (item[0][0], item[0][1])):
            if format_name not in known_formats:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="export",
                        description=f"Export manifest uses unknown format '{format_name}'.",
                        image_id=image_id,
                        suggested_repair="Migrate manifest to a known export format.",
                    )
                )
            if image_id not in image_ids:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="export",
                        description=f"Export manifest references missing image {image_id}.",
                        image_id=image_id,
                        suggested_repair="Delete orphan manifest or restore image record.",
                    )
                )
            if not manifest:
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="export",
                        description=f"Export manifest is empty for image {image_id} ({format_name}).",
                        image_id=image_id,
                        suggested_repair="Rebuild export manifest for this image.",
                    )
                )
                continue

            file_path = manifest.get("file_path")
            if not isinstance(file_path, str) or not file_path.strip():
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.WARNING,
                        subsystem="export",
                        description=f"Export manifest missing file_path for image {image_id} ({format_name}).",
                        image_id=image_id,
                        suggested_repair="Re-export image and rebuild manifest.",
                    )
                )
                continue

            if not Path(file_path).exists():
                issues.append(
                    IntegrityIssue(
                        severity=IntegritySeverity.ERROR,
                        subsystem="export",
                        description=f"Exported file is missing for image {image_id} ({format_name}).",
                        image_id=image_id,
                        file_path=file_path,
                        suggested_repair="Re-run export for missing artifact.",
                    )
                )
        return issues

    def _validate_path_text(self, path_text: str | None, *, subsystem: str, image_id: int | None) -> list[IntegrityIssue]:
        if path_text is None:
            return [
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem=subsystem,
                    description="Path is null.",
                    image_id=image_id,
                    suggested_repair="Restore missing path value from source data.",
                )
            ]

        issues: list[IntegrityIssue] = []
        if "\x00" in path_text:
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem=subsystem,
                    description="Path contains null byte.",
                    image_id=image_id,
                    file_path=path_text,
                    suggested_repair="Clean path string and remove control characters.",
                )
            )
        if len(path_text) > 4096:
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.ERROR,
                    subsystem=subsystem,
                    description="Path exceeds safe length threshold.",
                    image_id=image_id,
                    file_path=path_text,
                    suggested_repair="Shorten root and file names to reduce path length.",
                )
            )

        candidate = Path(path_text)
        if not candidate.is_absolute():
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem=subsystem,
                    description="Path is not absolute and may be non-portable.",
                    image_id=image_id,
                    file_path=path_text,
                    suggested_repair="Store canonical absolute paths in the database.",
                )
            )
        if any(part == ".." for part in candidate.parts):
            issues.append(
                IntegrityIssue(
                    severity=IntegritySeverity.WARNING,
                    subsystem=subsystem,
                    description="Path contains parent-directory traversal segment.",
                    image_id=image_id,
                    file_path=path_text,
                    suggested_repair="Normalize path and remove traversal segments.",
                )
            )
        return issues

    @staticmethod
    def _image_path(image) -> Path | None:
        path_text = image.current_path or image.original_path
        if not path_text:
            return None
        return Path(path_text)

    @staticmethod
    def _has_invalid_aliases(aliases: str | None) -> bool:
        if aliases is None:
            return False
        parts = [item.strip() for item in aliases.replace(";", ",").split(",")]
        if not parts:
            return False
        return any(not part for part in parts)
