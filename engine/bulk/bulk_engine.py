from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from engine.bulk.bulk_exceptions import BulkCancellationError, BulkExecutionError, BulkRollbackError, BulkValidationError
from engine.bulk.bulk_models import (
    BulkBatch,
    BulkBatchStatus,
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
from engine.collections.collection_models import CollectionKind
from engine.config import settings
from engine.database.session import UnitOfWork
from engine.logging import get_logger
from engine.organizer.organizer_models import OrganizationResult, OrganizationRule
from engine.organizer.organizer_service import OrganizerService
from engine.rename.rename_models import RenameResult, RenameRule
from engine.rename.rename_service import RenameService
from engine.repositories.bulk_repository import BulkRepository
from engine.repositories.collection_repository import CollectionRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.review_repository import ReviewRepository
from engine.repositories.tag_repository import TagRepository
from engine.review.review_models import ReviewDecisionType, ReviewStatus


class BulkEngine:
    """Coordinates deterministic batch operations across multiple images."""

    def __init__(
        self,
        *,
        repository: BulkRepository | None = None,
        callback: Callable[[object], None] | None = None,
    ) -> None:
        self.repository = repository or BulkRepository()
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = BulkStatistics()

    def preview_delete(self, image_ids: Iterable[int]) -> BulkResult:
        return self.delete_images(image_ids, dry_run=True)

    def preview_move(self, image_ids: Iterable[int], destination_directory: Path | str) -> BulkResult:
        return self.move_images(image_ids, destination_directory, dry_run=True)

    def preview_copy(self, image_ids: Iterable[int], destination_directory: Path | str) -> BulkResult:
        return self.copy_images(image_ids, destination_directory, dry_run=True)

    def preview_rename(self, image_ids: Iterable[int], *, rule: RenameRule | None = None) -> BulkResult:
        return self.rename_images(image_ids, rule=rule, dry_run=True)

    def preview_organize(
        self,
        image_ids: Iterable[int],
        *,
        rules: list[OrganizationRule] | None = None,
    ) -> BulkResult:
        return self.organize_images(image_ids, rules=rules, dry_run=True)

    def delete_images(
        self,
        image_ids: Iterable[int],
        *,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(operation_type=BulkOperationType.DELETE, image_ids=list(image_ids))
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def move_images(
        self,
        image_ids: Iterable[int],
        destination_directory: Path | str,
        *,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(
            operation_type=BulkOperationType.MOVE,
            image_ids=list(image_ids),
            target_directory=Path(destination_directory),
        )
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def copy_images(
        self,
        image_ids: Iterable[int],
        destination_directory: Path | str,
        *,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(
            operation_type=BulkOperationType.COPY,
            image_ids=list(image_ids),
            target_directory=Path(destination_directory),
        )
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def rename_images(
        self,
        image_ids: Iterable[int],
        *,
        rule: RenameRule | None = None,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(operation_type=BulkOperationType.RENAME, image_ids=list(image_ids), rename_rule=rule)
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def invoke_rename(self, image_ids: Iterable[int], *, rule: RenameRule | None = None, dry_run: bool = False) -> BulkResult:
        return self.rename_images(image_ids, rule=rule, dry_run=dry_run)

    def organize_images(
        self,
        image_ids: Iterable[int],
        *,
        rules: list[OrganizationRule] | None = None,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(operation_type=BulkOperationType.ORGANIZE, image_ids=list(image_ids), organizer_rules=rules)
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def invoke_organize(
        self,
        image_ids: Iterable[int],
        *,
        rules: list[OrganizationRule] | None = None,
        dry_run: bool = False,
    ) -> BulkResult:
        return self.organize_images(image_ids, rules=rules, dry_run=dry_run)

    def assign_tags(
        self,
        image_ids: Iterable[int],
        *,
        tag_name: str,
        tag_category: str | None = None,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(
            operation_type=BulkOperationType.TAG_ASSIGN,
            image_ids=list(image_ids),
            tag_name=tag_name,
            tag_category=tag_category,
        )
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def remove_tags(
        self,
        image_ids: Iterable[int],
        *,
        tag_name: str,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(operation_type=BulkOperationType.TAG_REMOVE, image_ids=list(image_ids), tag_name=tag_name)
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def assign_collection(
        self,
        image_ids: Iterable[int],
        *,
        collection_id: int,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(
            operation_type=BulkOperationType.COLLECTION_ASSIGN,
            image_ids=list(image_ids),
            collection_id=collection_id,
        )
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def approve_reviews(
        self,
        review_ids: Iterable[int],
        *,
        reviewer: str | None = None,
        reason: str | None = None,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(
            operation_type=BulkOperationType.REVIEW_APPROVE,
            review_ids=list(review_ids),
            reviewer=reviewer,
            reason=reason,
        )
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def reject_reviews(
        self,
        review_ids: Iterable[int],
        *,
        reviewer: str | None = None,
        reason: str | None = None,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        request = BulkRequest(
            operation_type=BulkOperationType.REVIEW_REJECT,
            review_ids=list(review_ids),
            reviewer=reviewer,
            reason=reason,
        )
        return self.execute(request, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def delete_batch(self, batch_id: str) -> None:
        batch = self.repository.get_batch(batch_id)
        if batch is None:
            return
        batch.cancel_requested = True
        batch.status = BulkBatchStatus.CANCELLED
        batch.updated_at = datetime.now(timezone.utc)
        self.repository.update_batch(batch)

    def cancel_batch(self, batch_id: str) -> None:
        self.delete_batch(batch_id)

    def resume_batch(self, batch_id: str) -> BulkResult:
        batch = self.repository.get_batch(batch_id)
        if batch is None:
            raise BulkValidationError(f"Bulk batch not found: {batch_id}")
        if batch.request is None:
            raise BulkValidationError(f"Bulk batch has no request: {batch_id}")
        batch.cancel_requested = False
        batch.status = BulkBatchStatus.RUNNING
        batch.updated_at = datetime.now(timezone.utc)
        self.repository.update_batch(batch)
        self.statistics.increment_batches_resumed()
        return self._execute_batch(batch, dry_run=False, resume=True)

    def preview_bulk_request(self, request: BulkRequest) -> BulkResult:
        return self.execute(request, dry_run=True)

    def execute(
        self,
        request: BulkRequest,
        *,
        dry_run: bool = False,
        resume: bool = False,
        batch_id: str | None = None,
    ) -> BulkResult:
        existing_batch = self.repository.get_batch(batch_id) if batch_id is not None else None
        if resume and existing_batch is not None:
            existing_batch.cancel_requested = False
            existing_batch.status = BulkBatchStatus.RUNNING
            existing_batch.updated_at = datetime.now(timezone.utc)
            self.repository.update_batch(existing_batch)
            if dry_run:
                self.statistics.increment_dry_run_batches()
                return self._build_result(existing_batch, dry_run=True, applied=False, resumed=True)
            self.statistics.increment_batches_resumed()
            return self._execute_batch(existing_batch, dry_run=False, resume=True)

        if not request.image_ids and not request.review_ids:
            batch = BulkBatch(batch_id=batch_id or str(uuid4()), request=request)
            self.repository.save_batch(batch)
            return BulkResult(
                batch_id=batch.batch_id,
                operation_type=request.operation_type,
                items=[],
                failures=[],
                dry_run=dry_run,
                applied=not dry_run,
                status=BulkBatchStatus.COMPLETED,
            )

        batch = self._build_batch(request, batch_id=batch_id)
        self.repository.save_batch(batch)
        if dry_run:
            self.statistics.increment_dry_run_batches()
            return self._build_result(batch, dry_run=True, applied=False, resumed=resume)

        if resume and batch.status in {BulkBatchStatus.CANCELLED, BulkBatchStatus.PARTIAL, BulkBatchStatus.FAILED}:
            self.statistics.increment_batches_resumed()

        return self._execute_batch(batch, dry_run=False, resume=resume)

    def rollback_last_batch(self) -> BulkResult | None:
        batches = sorted(self.repository.list_batches(), key=lambda batch: batch.created_at)
        if not batches:
            return None
        last_batch = batches[-1]
        if not last_batch.rollback_records:
            return None

        restored_records: list[BulkRollbackRecord] = []
        with UnitOfWork():
            image_repo = ImageRepository()
            tag_repo = TagRepository()
            collection_repo = CollectionRepository()
            review_repo = ReviewRepository()
            for record in reversed(last_batch.rollback_records):
                self._rollback_record(
                    record,
                    image_repo=image_repo,
                    tag_repo=tag_repo,
                    collection_repo=collection_repo,
                    review_repo=review_repo,
                )
                restored_records.append(record)

        last_batch.status = BulkBatchStatus.ROLLED_BACK
        last_batch.updated_at = datetime.now(timezone.utc)
        self.repository.update_batch(last_batch)
        self.statistics.increment_batches_rolled_back()
        return BulkResult(
            batch_id=last_batch.batch_id,
            operation_type=last_batch.request.operation_type if last_batch.request else BulkOperationType.DELETE,
            items=last_batch.items,
            failures=last_batch.failures,
            dry_run=False,
            applied=False,
            rolled_back=True,
            status=BulkBatchStatus.ROLLED_BACK,
            rollback_records=restored_records,
        )

    def _build_batch(self, request: BulkRequest, *, batch_id: str | None = None) -> BulkBatch:
        normalized_request = self._normalize_request(request)
        resolved_batch_id = batch_id or str(uuid4())
        items = self._build_items(normalized_request, batch_id=resolved_batch_id)
        batch = BulkBatch(batch_id=resolved_batch_id, request=normalized_request, items=items)
        self.statistics.increment_batches_created()
        self.statistics.increment_total_items(len(items))
        return batch

    def _normalize_request(self, request: BulkRequest) -> BulkRequest:
        normalized = BulkRequest(
            operation_type=request.operation_type,
            image_ids=sorted(int(image_id) for image_id in request.image_ids),
            review_ids=sorted(int(review_id) for review_id in request.review_ids),
            target_directory=Path(request.target_directory) if request.target_directory is not None else None,
            target_path=Path(request.target_path) if request.target_path is not None else None,
            tag_name=request.tag_name.strip() if request.tag_name else None,
            tag_category=request.tag_category.strip() if request.tag_category else None,
            collection_id=request.collection_id,
            reviewer=request.reviewer,
            reason=request.reason,
            rename_rule=request.rename_rule,
            organizer_rules=request.organizer_rules,
            metadata=dict(request.metadata),
        )
        return normalized

    def _build_items(self, request: BulkRequest, *, batch_id: str) -> list[BulkItem]:
        if request.operation_type in {
            BulkOperationType.REVIEW_APPROVE,
            BulkOperationType.REVIEW_REJECT,
        }:
            return self._build_review_items(request)

        if request.operation_type in {
            BulkOperationType.RENAME,
            BulkOperationType.ORGANIZE,
        }:
            return self._build_image_items(request, batch_id=batch_id, preview_only=True)

        return self._build_image_items(request, batch_id=batch_id)

    def _build_image_items(self, request: BulkRequest, *, batch_id: str, preview_only: bool = False) -> list[BulkItem]:
        items: list[BulkItem] = []
        seen: set[int] = set()
        with UnitOfWork():
            image_repo = ImageRepository()
            for index, image_id in enumerate(request.image_ids):
                if image_id in seen:
                    self.statistics.increment_duplicate_requests()
                    items.append(
                        BulkItem(
                            entity_id=image_id,
                            operation_type=request.operation_type,
                            status=BulkItemStatus.SKIPPED,
                            reason="Duplicate request",
                            batch_index=index,
                        )
                    )
                    continue
                seen.add(image_id)

                image = image_repo.get_by_id(image_id)
                source_path = self._image_path(image)
                target_path = self._preview_target_path(request, image, batch_id=batch_id, index=index) if preview_only else self._target_path(request, image, batch_id=batch_id, index=index)
                metadata = self._build_item_metadata(request, image_id=image_id, source_path=source_path, target_path=target_path)
                items.append(
                    BulkItem(
                        entity_id=image_id,
                        operation_type=request.operation_type,
                        source_path=source_path,
                        target_path=target_path,
                        metadata=metadata,
                        batch_index=index,
                    )
                )
        return items

    def _build_review_items(self, request: BulkRequest) -> list[BulkItem]:
        items: list[BulkItem] = []
        seen: set[int] = set()
        review_repo = ReviewRepository()
        for index, review_id in enumerate(request.review_ids):
            if review_id in seen:
                self.statistics.increment_duplicate_requests()
                items.append(
                    BulkItem(
                        entity_id=review_id,
                        operation_type=request.operation_type,
                        status=BulkItemStatus.SKIPPED,
                        reason="Duplicate request",
                        batch_index=index,
                    )
                )
                continue
            seen.add(review_id)
            review = review_repo.get_review_item(review_id)
            source_path = review.source_path if review is not None else None
            items.append(
                BulkItem(
                    entity_id=review_id,
                    operation_type=request.operation_type,
                    source_path=source_path,
                    metadata={"review_id": review_id},
                    batch_index=index,
                )
            )
        return items

    def _execute_batch(self, batch: BulkBatch, *, dry_run: bool, resume: bool) -> BulkResult:
        if batch.request is None:
            raise BulkValidationError(f"Bulk batch has no request: {batch.batch_id}")

        batch.status = BulkBatchStatus.RUNNING
        batch.updated_at = datetime.now(timezone.utc)
        self.repository.update_batch(batch)

        if dry_run:
            return self._build_result(batch, dry_run=True, applied=False, resumed=resume)

        try:
            with UnitOfWork():
                image_repo = ImageRepository()
                tag_repo = TagRepository()
                collection_repo = CollectionRepository()
                review_repo = ReviewRepository()
                rename_service = RenameService()
                organizer_service = OrganizerService()

                if batch.request.operation_type in {BulkOperationType.RENAME, BulkOperationType.ORGANIZE}:
                    self._execute_batch_operation(
                        batch,
                        image_repo=image_repo,
                        tag_repo=tag_repo,
                        collection_repo=collection_repo,
                        review_repo=review_repo,
                        rename_service=rename_service,
                        organizer_service=organizer_service,
                    )
                else:
                    self._execute_item_by_item(
                        batch,
                        image_repo=image_repo,
                        tag_repo=tag_repo,
                        collection_repo=collection_repo,
                        review_repo=review_repo,
                    )
        except Exception as exc:
            batch.status = BulkBatchStatus.FAILED
            batch.updated_at = datetime.now(timezone.utc)
            self.repository.update_batch(batch)
            raise BulkExecutionError(str(exc)) from exc

        batch.updated_at = datetime.now(timezone.utc)
        if batch.cancel_requested:
            batch.status = BulkBatchStatus.CANCELLED
            self.statistics.increment_batches_cancelled()
        elif batch.failures:
            batch.status = BulkBatchStatus.PARTIAL
            self.statistics.increment_partial_failures()
        else:
            batch.status = BulkBatchStatus.COMPLETED
            self.statistics.increment_batches_completed()
        self.repository.update_batch(batch)
        return self._build_result(batch, dry_run=False, applied=True, resumed=resume, cancelled=batch.cancel_requested)

    def _execute_item_by_item(
        self,
        batch: BulkBatch,
        *,
        image_repo: ImageRepository,
        tag_repo: TagRepository,
        collection_repo: CollectionRepository,
        review_repo: ReviewRepository,
    ) -> None:
        request = batch.request
        assert request is not None

        for index in range(batch.next_index, len(batch.items)):
            if batch.cancel_requested:
                break

            item = batch.items[index]
            if item.status == BulkItemStatus.SKIPPED:
                self.statistics.increment_processed_items()
                self.statistics.increment_skipped_items()
                batch.next_index = index + 1
                self._emit_progress(batch, item)
                continue

            try:
                self._process_item(
                    batch=batch,
                    item=item,
                    request=request,
                    image_repo=image_repo,
                    tag_repo=tag_repo,
                    collection_repo=collection_repo,
                    review_repo=review_repo,
                )
                item.status = BulkItemStatus.SUCCEEDED
                self.statistics.increment_succeeded_items()
            except BulkCancellationError:
                item.status = BulkItemStatus.CANCELLED
                self.statistics.increment_cancelled_items()
                batch.cancel_requested = True
                break
            except Exception as exc:
                item.status = BulkItemStatus.FAILED
                item.reason = str(exc)
                self.statistics.increment_failed_items()
                failure = BulkFailure(
                    entity_id=item.entity_id,
                    operation_type=item.operation_type,
                    error=str(exc),
                    source_path=item.source_path,
                    target_path=item.target_path,
                    batch_index=index,
                )
                self.repository.append_failure(batch.batch_id, failure)
            finally:
                batch.next_index = index + 1
                self.statistics.increment_processed_items()
                batch.updated_at = datetime.now(timezone.utc)
                self.repository.update_batch(batch)
                self._emit_progress(batch, item)

    def _execute_batch_operation(
        self,
        batch: BulkBatch,
        *,
        image_repo: ImageRepository,
        tag_repo: TagRepository,
        collection_repo: CollectionRepository,
        review_repo: ReviewRepository,
        rename_service: RenameService,
        organizer_service: OrganizerService,
    ) -> None:
        request = batch.request
        assert request is not None

        if batch.cancel_requested:
            raise BulkCancellationError(f"Bulk batch cancelled before execution: {batch.batch_id}")

        paths = [item.source_path for item in batch.items if item.status == BulkItemStatus.PENDING and item.source_path is not None]
        if request.operation_type == BulkOperationType.RENAME:
            rename_result = rename_service.apply_rename(paths, rule=request.rename_rule, dry_run=False)
            self._apply_path_result(batch, rename_result.previews)
            return

        if request.operation_type == BulkOperationType.ORGANIZE:
            organizer_result = organizer_service.apply_organize(paths, rules=request.organizer_rules, dry_run=False)
            self._apply_path_result(batch, organizer_result.previews)
            return

        self._execute_item_by_item(
            batch,
            image_repo=image_repo,
            tag_repo=tag_repo,
            collection_repo=collection_repo,
            review_repo=review_repo,
        )

    def _apply_path_result(self, batch: BulkBatch, results: list[Any]) -> None:
        request = batch.request
        assert request is not None

        for index, item in enumerate(batch.items):
            if item.status == BulkItemStatus.SKIPPED:
                self.statistics.increment_processed_items()
                self.statistics.increment_skipped_items()
                self._emit_progress(batch, item)
                continue
            if index >= len(results):
                item.status = BulkItemStatus.FAILED
                item.reason = "Missing operation result"
                failure = BulkFailure(
                    entity_id=item.entity_id,
                    operation_type=item.operation_type,
                    error="Missing operation result",
                    source_path=item.source_path,
                    target_path=item.target_path,
                    batch_index=index,
                )
                self.repository.append_failure(batch.batch_id, failure)
                self.statistics.increment_failed_items()
                self.statistics.increment_processed_items()
                self._emit_progress(batch, item)
                continue

            result = results[index]
            target_path = getattr(result, "target_path", None) or getattr(result, "destination_path", None)
            item.target_path = Path(target_path) if target_path is not None else item.target_path
            try:
                self._record_path_rollback(batch, item, request)
                item.status = BulkItemStatus.SUCCEEDED
                self.statistics.increment_succeeded_items()
            except Exception as exc:
                item.status = BulkItemStatus.FAILED
                item.reason = str(exc)
                failure = BulkFailure(
                    entity_id=item.entity_id,
                    operation_type=item.operation_type,
                    error=str(exc),
                    source_path=item.source_path,
                    target_path=item.target_path,
                    batch_index=index,
                )
                self.repository.append_failure(batch.batch_id, failure)
                self.statistics.increment_failed_items()

            self.statistics.increment_processed_items()
            batch.next_index = index + 1
            batch.updated_at = datetime.now(timezone.utc)
            self.repository.update_batch(batch)
            self._emit_progress(batch, item)

    def _process_item(
        self,
        *,
        batch: BulkBatch,
        item: BulkItem,
        request: BulkRequest,
        image_repo: ImageRepository,
        tag_repo: TagRepository,
        collection_repo: CollectionRepository,
        review_repo: ReviewRepository,
    ) -> None:
        image = image_repo.get_by_id(item.entity_id) if item.operation_type not in {BulkOperationType.REVIEW_APPROVE, BulkOperationType.REVIEW_REJECT} else None

        if item.operation_type == BulkOperationType.DELETE:
            self._delete_item(batch=batch, item=item, image=image, image_repo=image_repo)
        elif item.operation_type == BulkOperationType.MOVE:
            self._move_item(batch=batch, item=item, image=image, image_repo=image_repo)
        elif item.operation_type == BulkOperationType.COPY:
            self._copy_item(batch=batch, item=item, image=image, image_repo=image_repo)
        elif item.operation_type == BulkOperationType.TAG_ASSIGN:
            self._assign_tag(batch=batch, item=item, image=image, image_repo=image_repo, tag_repo=tag_repo, request=request)
        elif item.operation_type == BulkOperationType.TAG_REMOVE:
            self._remove_tag(batch=batch, item=item, image=image, image_repo=image_repo, tag_repo=tag_repo, request=request)
        elif item.operation_type == BulkOperationType.COLLECTION_ASSIGN:
            self._assign_collection(batch=batch, item=item, image=image, image_repo=image_repo, collection_repo=collection_repo, request=request)
        elif item.operation_type == BulkOperationType.REVIEW_APPROVE:
            self._decide_review(batch=batch, item=item, review_repo=review_repo, decision=ReviewDecisionType.APPROVE, request=request)
        elif item.operation_type == BulkOperationType.REVIEW_REJECT:
            self._decide_review(batch=batch, item=item, review_repo=review_repo, decision=ReviewDecisionType.REJECT, request=request)
        else:
            raise BulkExecutionError(f"Unsupported operation type: {item.operation_type}")

    def _delete_item(self, *, batch: BulkBatch, item: BulkItem, image, image_repo: ImageRepository) -> None:
        if image is None or item.source_path is None:
            raise BulkExecutionError(f"Image not found: {item.entity_id}")
        source_path = Path(item.source_path)
        if not source_path.exists():
            raise BulkExecutionError(f"Source file does not exist: {source_path}")
        backup_path = self._build_backup_path(batch.batch_id, item.entity_id, source_path, kind="delete")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.rename(backup_path)
        previous_value = {
            "current_path": image.current_path,
            "filename": image.filename,
            "extension": image.extension,
        }
        image.current_path = str(backup_path)
        image.filename = backup_path.name
        image.extension = backup_path.suffix
        image_repo.commit()
        self._append_rollback(
            batch=batch,
            item=item,
            previous_value=previous_value,
            restored_value={"current_path": str(source_path), "filename": source_path.name},
            target_path=backup_path,
        )
        item.target_path = backup_path

    def _move_item(self, *, batch: BulkBatch, item: BulkItem, image, image_repo: ImageRepository) -> None:
        if image is None or item.source_path is None or batch.request is None or batch.request.target_directory is None:
            raise BulkExecutionError(f"Image or target directory missing for move: {item.entity_id}")
        source_path = Path(item.source_path)
        if not source_path.exists():
            raise BulkExecutionError(f"Source file does not exist: {source_path}")
        destination = self._resolve_destination_path(
            batch_id=batch.batch_id,
            base_path=Path(batch.request.target_directory),
            source_path=source_path,
            item_id=item.entity_id,
            kind="move",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_path.rename(destination)
        previous_value = {
            "current_path": image.current_path,
            "filename": image.filename,
            "extension": image.extension,
        }
        image.current_path = str(destination)
        image.filename = destination.name
        image.extension = destination.suffix
        image_repo.commit()
        self._append_rollback(
            batch=batch,
            item=item,
            previous_value=previous_value,
            restored_value={"current_path": str(source_path), "filename": source_path.name},
            target_path=destination,
        )
        item.target_path = destination

    def _copy_item(self, *, batch: BulkBatch, item: BulkItem, image, image_repo: ImageRepository) -> None:
        if image is None or item.source_path is None or batch.request is None or batch.request.target_directory is None:
            raise BulkExecutionError(f"Image or target directory missing for copy: {item.entity_id}")
        source_path = Path(item.source_path)
        if not source_path.exists():
            raise BulkExecutionError(f"Source file does not exist: {source_path}")
        destination = self._resolve_destination_path(
            batch_id=batch.batch_id,
            base_path=Path(batch.request.target_directory),
            source_path=source_path,
            item_id=item.entity_id,
            kind="copy",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_path.read_bytes())
        new_image = image_repo.create_image(original_path=str(destination), filename=destination.name, extension=destination.suffix)
        new_image.current_path = str(destination)
        new_image.width = image.width
        new_image.height = image.height
        new_image.filesize = image.filesize
        new_image.sha256 = image.sha256
        new_image.phash = image.phash
        new_image.series = image.series
        new_image.characters = list(image.characters)
        new_image.tags = list(image.tags)
        image_repo.commit()
        self._append_rollback(
            batch=batch,
            item=item,
            previous_value={"copied_image_id": new_image.id},
            restored_value={"delete_image_id": new_image.id},
            target_path=destination,
        )
        item.target_path = destination
        item.metadata["copied_image_id"] = new_image.id

    def _assign_tag(
        self,
        *,
        batch: BulkBatch,
        item: BulkItem,
        image,
        image_repo: ImageRepository,
        tag_repo: TagRepository,
        request: BulkRequest,
    ) -> None:
        if image is None or request.tag_name is None:
            raise BulkExecutionError(f"Image or tag missing for tag assignment: {item.entity_id}")
        tag = next((candidate for candidate in tag_repo.list_tags() if candidate.name == request.tag_name), None)
        if tag is None:
            tag = tag_repo.create_tag(name=request.tag_name, category=request.tag_category)
        previous_value = {"tag_ids": [existing.id for existing in image.tags]}
        tag_repo.assign_tag(image, tag)
        image_repo.commit()
        self._append_rollback(
            batch=batch,
            item=item,
            previous_value=previous_value,
            restored_value={"remove_tag_id": tag.id},
        )
        item.metadata["tag_id"] = tag.id

    def _remove_tag(
        self,
        *,
        batch: BulkBatch,
        item: BulkItem,
        image,
        image_repo: ImageRepository,
        tag_repo: TagRepository,
        request: BulkRequest,
    ) -> None:
        if image is None or request.tag_name is None:
            raise BulkExecutionError(f"Image or tag missing for tag removal: {item.entity_id}")
        tag = next((candidate for candidate in tag_repo.list_tags() if candidate.name == request.tag_name), None)
        if tag is None:
            raise BulkExecutionError(f"Tag not found: {request.tag_name}")
        previous_value = {"tag_ids": [existing.id for existing in image.tags]}
        tag_repo.remove_tag(image, tag)
        image_repo.commit()
        self._append_rollback(
            batch=batch,
            item=item,
            previous_value=previous_value,
            restored_value={"add_tag_id": tag.id},
        )
        item.metadata["tag_id"] = tag.id

    def _assign_collection(
        self,
        *,
        batch: BulkBatch,
        item: BulkItem,
        image,
        image_repo: ImageRepository,
        collection_repo: CollectionRepository,
        request: BulkRequest,
    ) -> None:
        if image is None or request.collection_id is None:
            raise BulkExecutionError(f"Image or collection missing for collection assignment: {item.entity_id}")
        previous_value = {"collection_ids": [candidate.collection_id for candidate in collection_repo.list_collections() if item.entity_id in candidate.image_ids]}
        changed = collection_repo.add_image(request.collection_id, item.entity_id)
        if not changed:
            raise BulkExecutionError(f"Image already assigned to collection: {item.entity_id}")
        image_repo.commit()
        self._append_rollback(
            batch=batch,
            item=item,
            previous_value=previous_value,
            restored_value={"remove_image_from_collection": request.collection_id},
        )
        item.metadata["collection_id"] = request.collection_id

    def _decide_review(
        self,
        *,
        batch: BulkBatch,
        item: BulkItem,
        review_repo: ReviewRepository,
        decision: ReviewDecisionType,
        request: BulkRequest,
    ) -> None:
        review = review_repo.get_review_item(item.entity_id)
        if review is None:
            raise BulkExecutionError(f"Review not found: {item.entity_id}")
        previous_value = {"status": review.status.value, "current_value": review.current_value}
        decision_record = review_repo.apply_review_decision(
            item.entity_id,
            decision=decision,
            reviewer=request.reviewer,
            reason=request.reason,
            batch_id=batch.batch_id,
        )
        self._append_rollback(
            batch=batch,
            item=item,
            previous_value=previous_value,
            restored_value={"status": decision_record.previous_status.value, "current_value": decision_record.previous_value},
        )
        item.metadata["review_decision"] = decision.value

    def _record_rollback_record(
        self,
        *,
        batch: BulkBatch,
        item: BulkItem,
        previous_value: Any,
        restored_value: Any,
        target_path: Path | None = None,
    ) -> None:
        record = BulkRollbackRecord(
            batch_id=batch.batch_id,
            entity_id=item.entity_id,
            operation_type=item.operation_type,
            source_path=item.source_path,
            target_path=target_path or item.target_path,
            previous_value=previous_value,
            restored_value=restored_value,
            metadata=dict(item.metadata),
        )
        self.repository.append_rollback_record(batch.batch_id, record)

    def _append_rollback(
        self,
        *,
        batch: BulkBatch,
        item: BulkItem,
        previous_value: Any,
        restored_value: Any,
        target_path: Path | None = None,
    ) -> None:
        self._record_rollback_record(
            batch=batch,
            item=item,
            previous_value=previous_value,
            restored_value=restored_value,
            target_path=target_path,
        )
        batch.rollback_records = self.repository.list_rollback_records(batch.batch_id)

    def _rollback_record(
        self,
        record: BulkRollbackRecord,
        *,
        image_repo: ImageRepository,
        tag_repo: TagRepository,
        collection_repo: CollectionRepository,
        review_repo: ReviewRepository,
    ) -> None:
        if record.operation_type == BulkOperationType.DELETE:
            if record.target_path is not None and record.source_path is not None and Path(record.target_path).exists():
                Path(record.source_path).parent.mkdir(parents=True, exist_ok=True)
                Path(record.target_path).rename(Path(record.source_path))
            image = image_repo.get_by_id(record.entity_id)
            if image is not None and isinstance(record.previous_value, dict):
                image.current_path = record.previous_value.get("current_path")
                image.filename = record.previous_value.get("filename", image.filename)
                image.extension = record.previous_value.get("extension", image.extension)
                image_repo.commit()
            return

        if record.operation_type in {BulkOperationType.MOVE, BulkOperationType.RENAME, BulkOperationType.ORGANIZE}:
            if record.target_path is not None and record.source_path is not None and Path(record.target_path).exists():
                Path(record.source_path).parent.mkdir(parents=True, exist_ok=True)
                Path(record.target_path).rename(Path(record.source_path))
            image = image_repo.get_by_id(record.entity_id)
            if image is not None and isinstance(record.previous_value, dict):
                image.current_path = record.previous_value.get("current_path")
                image.filename = record.previous_value.get("filename", image.filename)
                image.extension = record.previous_value.get("extension", image.extension)
                image_repo.commit()
            return

        if record.operation_type == BulkOperationType.COPY:
            new_image_id = None
            if isinstance(record.previous_value, dict):
                new_image_id = record.previous_value.get("copied_image_id")
            if isinstance(new_image_id, int):
                copied_image = image_repo.get_by_id(new_image_id)
                if copied_image is not None:
                    image_repo.delete(copied_image)
                    image_repo.commit()
                if record.target_path is not None and Path(record.target_path).exists():
                    Path(record.target_path).unlink(missing_ok=True)
            return

        if record.operation_type == BulkOperationType.TAG_ASSIGN:
            image = image_repo.get_by_id(record.entity_id)
            if image is None:
                return
            tag_id = None
            if isinstance(record.restored_value, dict):
                tag_id = record.restored_value.get("remove_tag_id")
            if isinstance(tag_id, int):
                tag = next((candidate for candidate in tag_repo.list_tags() if candidate.id == tag_id), None)
                if tag is not None:
                    tag_repo.remove_tag(image, tag)
            image_repo.commit()
            return

        if record.operation_type == BulkOperationType.TAG_REMOVE:
            image = image_repo.get_by_id(record.entity_id)
            if image is None:
                return
            tag_id = None
            if isinstance(record.restored_value, dict):
                tag_id = record.restored_value.get("add_tag_id")
            if isinstance(tag_id, int):
                tag = next((candidate for candidate in tag_repo.list_tags() if candidate.id == tag_id), None)
                if tag is not None:
                    tag_repo.assign_tag(image, tag)
            image_repo.commit()
            return

        if record.operation_type == BulkOperationType.COLLECTION_ASSIGN:
            collection_id = None
            if isinstance(record.restored_value, dict):
                collection_id = record.restored_value.get("remove_image_from_collection")
            if isinstance(collection_id, int):
                collection_repo.remove_image(collection_id, record.entity_id)
            return

        if record.operation_type in {BulkOperationType.REVIEW_APPROVE, BulkOperationType.REVIEW_REJECT}:
            review_store = getattr(review_repo, "_queue_reviews", {})
            review = review_store.get(record.entity_id)
            if review is None:
                return
            if isinstance(record.previous_value, dict):
                status_text = record.previous_value.get("status", ReviewStatus.PENDING.value)
                try:
                    review.status = ReviewStatus(status_text)
                except ValueError:
                    review.status = ReviewStatus.PENDING
                review.current_value = record.previous_value.get("current_value")
                review.reviewer = None
                review.decision_reason = None
            return

        raise BulkRollbackError(f"Unsupported rollback operation: {record.operation_type}")

    def _build_result(
        self,
        batch: BulkBatch,
        *,
        dry_run: bool,
        applied: bool,
        resumed: bool = False,
        cancelled: bool = False,
    ) -> BulkResult:
        return BulkResult(
            batch_id=batch.batch_id,
            operation_type=batch.request.operation_type if batch.request is not None else BulkOperationType.DELETE,
            items=list(batch.items),
            failures=list(batch.failures),
            dry_run=dry_run,
            applied=applied,
            rolled_back=batch.status == BulkBatchStatus.ROLLED_BACK,
            cancelled=cancelled,
            resumed=resumed,
            status=batch.status,
            rollback_records=list(batch.rollback_records),
        )

    def _build_item_metadata(
        self,
        request: BulkRequest,
        *,
        image_id: int,
        source_path: Path | None,
        target_path: Path | None,
    ) -> dict[str, Any]:
        return {
            "image_id": image_id,
            "source_path": str(source_path) if source_path is not None else None,
            "target_path": str(target_path) if target_path is not None else None,
            "operation_type": request.operation_type.value,
        }

    def _image_path(self, image) -> Path | None:
        if image is None:
            return None
        path_text = image.current_path or image.original_path
        return Path(path_text) if path_text else None

    def _target_path(self, request: BulkRequest, image, *, batch_id: str, index: int) -> Path | None:
        if image is None:
            return None
        source_path = self._image_path(image)
        if source_path is None:
            return None
        if request.operation_type == BulkOperationType.DELETE:
            return self._build_backup_path(batch_id, image.id, source_path, kind="delete")
        if request.operation_type in {BulkOperationType.MOVE, BulkOperationType.COPY}:
            if request.target_directory is None:
                return None
            return self._resolve_destination_path(
                batch_id=batch_id,
                base_path=Path(request.target_directory),
                source_path=source_path,
                item_id=image.id,
                kind=request.operation_type.value,
            )
        return source_path

    def _preview_target_path(self, request: BulkRequest, image, *, batch_id: str, index: int) -> Path | None:
        if image is None:
            return None
        source_path = self._image_path(image)
        if source_path is None:
            return None
        if request.operation_type == BulkOperationType.RENAME:
            rename_service = RenameService()
            preview = rename_service.preview_rename([source_path], rule=request.rename_rule)
            return preview[0].target_path if preview else source_path
        if request.operation_type == BulkOperationType.ORGANIZE:
            organizer_service = OrganizerService()
            preview = organizer_service.preview_organize([source_path], rules=request.organizer_rules)
            return preview.previews[0].destination_path if preview.previews else source_path
        return self._target_path(request, image, batch_id=batch_id, index=index)

    def _resolve_destination_path(
        self,
        *,
        batch_id: str,
        base_path: Path,
        source_path: Path,
        item_id: int,
        kind: str,
    ) -> Path:
        candidate = base_path / source_path.name
        if not candidate.exists():
            return candidate
        suffix = source_path.suffix
        stem = source_path.stem
        counter = 1
        while True:
            numbered = candidate.with_name(f"{stem}_{counter:03d}{suffix}")
            if not numbered.exists():
                return numbered
            counter += 1

    def _build_backup_path(self, batch_id: str, item_id: int, source_path: Path, *, kind: str) -> Path:
        backup_dir = settings.cache_directory / "bulk" / kind / batch_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        candidate = backup_dir / f"{item_id}_{source_path.name}"
        counter = 1
        while candidate.exists():
            candidate = backup_dir / f"{item_id}_{counter:03d}_{source_path.name}"
            counter += 1
        return candidate

    def _emit_progress(self, batch: BulkBatch, item: BulkItem) -> None:
        if self.callback is None:
            return
        processed = batch.processed
        total = batch.total
        percent = batch.progress_percentage
        self.callback(
            BulkProgress(
                batch_id=batch.batch_id,
                operation_type=batch.request.operation_type if batch.request else item.operation_type,
                processed=processed,
                total=total,
                percent=percent,
                entity_id=item.entity_id,
                batch_index=item.batch_index,
            )
        )
