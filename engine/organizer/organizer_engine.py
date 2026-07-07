from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from engine.logging import get_logger
from engine.organizer.organizer_exceptions import OrganizerApplyError, OrganizerRollbackError, OrganizerRuleError
from engine.organizer.organizer_models import (
    OrganizationPlan,
    OrganizationPreview,
    OrganizationResult,
    OrganizationRule,
    RollbackBatch,
    RollbackRecord,
)
from engine.organizer.organizer_statistics import OrganizerStatistics
from engine.repositories.organizer_repository import OrganizerRepository

_ILLEGAL_SEGMENT_CHARS = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_DUPLICATE_SPACES = re.compile(r"\s+")
_DUPLICATE_UNDERSCORES = re.compile(r"_+")


class OrganizerEngine:
    """Moves renamed files into organized directory structure using rules."""

    def __init__(
        self,
        *,
        repository: OrganizerRepository | None = None,
        callback: Callable[[object], None] | None = None,
        rules: list[OrganizationRule] | None = None,
    ) -> None:
        self.repository = repository or OrganizerRepository()
        self.callback = callback
        self.rules = list(rules or [])
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = OrganizerStatistics()
        self._last_rollback_batch: RollbackBatch | None = None

    def preview_organize(
        self,
        paths: Iterable[Path | str],
        *,
        rules: list[OrganizationRule] | None = None,
    ) -> OrganizationPlan:
        self.statistics = OrganizerStatistics()
        self.statistics.start()
        try:
            previews = self._build_previews(paths, rules=rules)
            return OrganizationPlan(previews=previews)
        finally:
            self.statistics.finish()

    def apply_organize(
        self,
        paths: Iterable[Path | str],
        *,
        rules: list[OrganizationRule] | None = None,
        dry_run: bool = False,
    ) -> OrganizationResult:
        self.statistics = OrganizerStatistics()
        self.statistics.start()
        batch_id = str(uuid4())

        previews = self._build_previews(paths, rules=rules)
        if dry_run:
            self.statistics.increment_dry_run()
            self.statistics.finish()
            return OrganizationResult(
                batch_id=batch_id,
                previews=previews,
                dry_run=True,
                applied=False,
                rolled_back=False,
            )

        operations = [preview for preview in previews if not preview.skipped and preview.source_path != preview.destination_path]
        if not operations:
            self.statistics.finish()
            return OrganizationResult(
                batch_id=batch_id,
                previews=previews,
                dry_run=False,
                applied=True,
                rolled_back=False,
            )

        temp_pairs: list[tuple[Path, OrganizationPreview]] = []
        finalized: list[OrganizationPreview] = []

        try:
            for index, preview in enumerate(operations, start=1):
                source = preview.source_path
                if not source.exists():
                    raise OrganizerApplyError(f"Source file does not exist: {source}")

                temp = source.with_name(f".ailm_organize_tmp_{batch_id}_{index}{source.suffix}")
                while temp.exists():
                    temp = source.with_name(f".ailm_organize_tmp_{batch_id}_{index}_{uuid4().hex[:6]}{source.suffix}")

                source.rename(temp)
                temp_pairs.append((temp, preview))

            for temp, preview in temp_pairs:
                preview.destination_path.parent.mkdir(parents=True, exist_ok=True)
                temp.rename(preview.destination_path)
                self.repository.update_image_path(preview.image_id, preview.destination_path)
                finalized.append(preview)
                self.statistics.increment_moved()

            self._last_rollback_batch = RollbackBatch(
                batch_id=batch_id,
                records=[
                    RollbackRecord(
                        image_id=preview.image_id,
                        source_path=preview.source_path,
                        destination_path=preview.destination_path,
                    )
                    for preview in finalized
                ],
            )

            return OrganizationResult(
                batch_id=batch_id,
                previews=previews,
                dry_run=False,
                applied=True,
                rolled_back=False,
            )
        except Exception as exc:
            self.statistics.increment_failed()
            self._best_effort_restore(temp_pairs=temp_pairs, finalized=finalized)
            if isinstance(exc, OrganizerApplyError):
                raise
            raise OrganizerApplyError(f"Failed to apply organization batch: {exc}") from exc
        finally:
            self.statistics.finish()

    def rollback_last_batch(self) -> OrganizationResult | None:
        if self._last_rollback_batch is None:
            return None

        batch = self._last_rollback_batch
        previews: list[OrganizationPreview] = []
        try:
            for record in reversed(batch.records):
                if not record.destination_path.exists():
                    raise OrganizerRollbackError(f"Cannot rollback missing destination: {record.destination_path}")

                record.source_path.parent.mkdir(parents=True, exist_ok=True)
                record.destination_path.rename(record.source_path)
                self.repository.update_image_path(record.image_id, record.source_path)
                self.statistics.increment_rolled_back()
                previews.append(
                    OrganizationPreview(
                        image_id=record.image_id,
                        source_path=record.destination_path,
                        destination_path=record.source_path,
                        rule_name="rollback",
                        sequence=0,
                    )
                )
        except Exception as exc:
            self.statistics.increment_failed()
            if isinstance(exc, OrganizerRollbackError):
                raise
            raise OrganizerRollbackError(f"Failed to rollback organization batch {batch.batch_id}: {exc}") from exc

        self._last_rollback_batch = None
        previews.reverse()
        return OrganizationResult(
            batch_id=batch.batch_id,
            previews=previews,
            dry_run=False,
            applied=False,
            rolled_back=True,
        )

    def _build_previews(
        self,
        paths: Iterable[Path | str],
        *,
        rules: list[OrganizationRule] | None,
    ) -> list[OrganizationPreview]:
        active_rules = sorted(list(rules or self.rules), key=lambda item: item.priority)
        if not active_rules:
            raise OrganizerRuleError("At least one organization rule is required")

        previews: list[OrganizationPreview] = []
        reserved_destinations: set[Path] = set()
        seen_sources: set[Path] = set()
        normalized_paths = sorted(Path(path).resolve() for path in paths)

        for sequence, source_path in enumerate(normalized_paths, start=1):
            self.statistics.increment_processed()

            if source_path in seen_sources:
                self.statistics.increment_duplicate_moves_prevented()
                self.statistics.increment_skipped()
                previews.append(
                    OrganizationPreview(
                        image_id=0,
                        source_path=source_path,
                        destination_path=source_path,
                        rule_name="duplicate",
                        sequence=sequence,
                        skipped=True,
                        reason="Duplicate source in same batch",
                    )
                )
                continue
            seen_sources.add(source_path)

            metadata_info = self.repository.get_organization_metadata(source_path)
            if metadata_info is None:
                self.statistics.increment_skipped()
                previews.append(
                    OrganizationPreview(
                        image_id=0,
                        source_path=source_path,
                        destination_path=source_path,
                        rule_name="missing",
                        sequence=sequence,
                        skipped=True,
                        reason="Image not found in repository",
                    )
                )
                continue

            image_id, metadata = metadata_info
            rule = self._select_rule(active_rules, metadata)
            if rule is None:
                self.statistics.increment_skipped()
                previews.append(
                    OrganizationPreview(
                        image_id=image_id,
                        source_path=source_path,
                        destination_path=source_path,
                        rule_name="none",
                        sequence=sequence,
                        skipped=True,
                        reason="No matching organization rule",
                    )
                )
                continue

            relative_dir = self._expand_template(rule.directory_template, metadata)
            destination_dir = source_path.parent / relative_dir
            destination_file = destination_dir / source_path.name

            if source_path.parent == destination_dir:
                self.statistics.increment_already_organized()
                self.statistics.increment_skipped()
                previews.append(
                    OrganizationPreview(
                        image_id=image_id,
                        source_path=source_path,
                        destination_path=destination_file,
                        rule_name=rule.name,
                        sequence=sequence,
                        skipped=True,
                        reason="Already organized",
                    )
                )
                continue

            resolved_destination, conflicted = self._resolve_collision(
                source_path=source_path,
                destination_path=destination_file,
                reserved_destinations=reserved_destinations,
            )
            reserved_destinations.add(resolved_destination)

            previews.append(
                OrganizationPreview(
                    image_id=image_id,
                    source_path=source_path,
                    destination_path=resolved_destination,
                    rule_name=rule.name,
                    sequence=sequence,
                    conflicted=conflicted,
                )
            )
            self.statistics.increment_previewed()
            if conflicted:
                self.statistics.increment_conflicts_resolved()

        return previews

    @staticmethod
    def _select_rule(rules: list[OrganizationRule], metadata: dict[str, str]) -> OrganizationRule | None:
        for rule in rules:
            if rule.can_apply(metadata):
                return rule
        fallback = [rule for rule in rules if rule.is_fallback]
        return fallback[0] if fallback else None

    def _expand_template(self, template: str, metadata: dict[str, str]) -> Path:
        placeholders = {
            "series": metadata.get("series") or metadata.get("unknown") or "unknown",
            "character": metadata.get("character") or metadata.get("unknown") or "unknown",
            "source": metadata.get("source") or metadata.get("unknown") or "unknown",
            "year": metadata.get("year") or metadata.get("unknown") or "unknown",
            "first_letter": metadata.get("first_letter") or metadata.get("unknown") or "unknown",
            "unknown": metadata.get("unknown") or "unknown",
        }

        expanded = template
        for key, value in placeholders.items():
            expanded = expanded.replace(f"{{{key}}}", self._sanitize_segment(value))

        parts = [self._sanitize_segment(part) for part in Path(expanded).parts if part not in {"", "."}]
        safe_parts = [part for part in parts if part not in {".."}]
        if not safe_parts:
            safe_parts = ["unknown"]
        return Path(*safe_parts)

    @staticmethod
    def _sanitize_segment(value: str) -> str:
        cleaned = _ILLEGAL_SEGMENT_CHARS.sub("_", value)
        cleaned = _DUPLICATE_SPACES.sub(" ", cleaned)
        cleaned = _DUPLICATE_UNDERSCORES.sub("_", cleaned)
        cleaned = cleaned.strip().strip(".")
        return cleaned or "unknown"

    def _resolve_collision(
        self,
        *,
        source_path: Path,
        destination_path: Path,
        reserved_destinations: set[Path],
    ) -> tuple[Path, bool]:
        candidate = destination_path
        conflicted = False
        counter = 1

        while self._is_conflict(source_path=source_path, destination_path=candidate, reserved_destinations=reserved_destinations):
            conflicted = True
            candidate = destination_path.with_name(f"{destination_path.stem}_{counter:03d}{destination_path.suffix}")
            counter += 1

        return candidate, conflicted

    @staticmethod
    def _is_conflict(*, source_path: Path, destination_path: Path, reserved_destinations: set[Path]) -> bool:
        normalized_destination = destination_path.resolve()
        normalized_reserved = {item.resolve() for item in reserved_destinations}
        if normalized_destination in normalized_reserved:
            return True
        if normalized_destination == source_path.resolve():
            return False
        return normalized_destination.exists()

    def _best_effort_restore(
        self,
        *,
        temp_pairs: list[tuple[Path, OrganizationPreview]],
        finalized: list[OrganizationPreview],
    ) -> None:
        for preview in reversed(finalized):
            if preview.destination_path.exists() and not preview.source_path.exists():
                try:
                    preview.destination_path.rename(preview.source_path)
                    self.repository.update_image_path(preview.image_id, preview.source_path)
                except Exception:
                    pass

        for temp, preview in reversed(temp_pairs):
            if temp.exists() and not preview.source_path.exists():
                try:
                    temp.rename(preview.source_path)
                except Exception:
                    pass
