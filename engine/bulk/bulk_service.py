from __future__ import annotations

from pathlib import Path

from engine.bulk.bulk_engine import BulkEngine
from engine.bulk.bulk_models import BulkResult
from engine.organizer.organizer_models import OrganizationRule
from engine.rename.rename_models import RenameRule


class BulkService:
    """Service facade for bulk operations."""

    def __init__(self, *, engine: BulkEngine | None = None) -> None:
        self.engine = engine or BulkEngine(callback=self._handle_event)

    def delete_images(self, image_ids: list[int], *, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.delete_images(image_ids, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def move_images(self, image_ids: list[int], destination_directory: Path | str, *, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.move_images(image_ids, destination_directory, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def copy_images(self, image_ids: list[int], destination_directory: Path | str, *, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.copy_images(image_ids, destination_directory, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def rename_images(self, image_ids: list[int], *, rule: RenameRule | None = None, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.rename_images(image_ids, rule=rule, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def organize_images(self, image_ids: list[int], *, rules: list[OrganizationRule] | None = None, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.organize_images(image_ids, rules=rules, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def assign_tags(self, image_ids: list[int], *, tag_name: str, tag_category: str | None = None, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.assign_tags(image_ids, tag_name=tag_name, tag_category=tag_category, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def remove_tags(self, image_ids: list[int], *, tag_name: str, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.remove_tags(image_ids, tag_name=tag_name, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def assign_collection(self, image_ids: list[int], *, collection_id: int, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.assign_collection(image_ids, collection_id=collection_id, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def approve_reviews(self, review_ids: list[int], *, reviewer: str | None = None, reason: str | None = None, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.approve_reviews(review_ids, reviewer=reviewer, reason=reason, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def reject_reviews(self, review_ids: list[int], *, reviewer: str | None = None, reason: str | None = None, dry_run: bool = False, resume: bool = False, batch_id: str | None = None) -> BulkResult:
        return self.engine.reject_reviews(review_ids, reviewer=reviewer, reason=reason, dry_run=dry_run, resume=resume, batch_id=batch_id)

    def rollback_last_batch(self) -> BulkResult | None:
        return self.engine.rollback_last_batch()

    def cancel_batch(self, batch_id: str) -> None:
        self.engine.cancel_batch(batch_id)

    def resume_batch(self, batch_id: str) -> BulkResult:
        return self.engine.resume_batch(batch_id)

    def _handle_event(self, event: object) -> None:
        return None
