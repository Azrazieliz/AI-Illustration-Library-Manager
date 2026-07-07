from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from engine.logging import get_logger
from engine.rename.rename_exceptions import RenameApplyError, RenameRollbackError
from engine.rename.rename_models import (
    RenameBatch,
    RenameBatchEntry,
    RenamePreview,
    RenameResult,
    RenameRule,
    RenameTemplate,
    build_safe_filename,
)
from engine.rename.rename_statistics import RenameStatistics
from engine.repositories.rename_repository import RenameRepository


class RenameEngine:
    """Generates deterministic rename previews and applies filesystem renames."""

    def __init__(
        self,
        *,
        repository: RenameRepository | None = None,
        callback: Callable[[object], None] | None = None,
        rule: RenameRule | None = None,
    ) -> None:
        self.repository = repository or RenameRepository()
        self.callback = callback
        self.rule = rule or RenameRule()
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = RenameStatistics()
        self._last_batch: RenameBatch | None = None

    def preview_rename(
        self,
        paths: Iterable[Path | str],
        *,
        rule: RenameRule | None = None,
    ) -> list[RenamePreview]:
        """Generate deterministic rename previews without touching filesystem."""
        self.statistics = RenameStatistics()
        self.statistics.start()
        try:
            previews = self._build_previews(paths, rule=rule)
            return previews
        finally:
            self.statistics.finish()

    def apply_rename(
        self,
        paths: Iterable[Path | str],
        *,
        rule: RenameRule | None = None,
        dry_run: bool = False,
    ) -> RenameResult:
        """Apply filesystem rename operations for provided paths."""
        self.statistics = RenameStatistics()
        self.statistics.start()
        batch_id = str(uuid4())

        previews = self._build_previews(paths, rule=rule)
        if dry_run:
            self.statistics.increment_dry_run()
            self.statistics.finish()
            return RenameResult(
                batch_id=batch_id,
                previews=previews,
                dry_run=True,
                applied=False,
                rolled_back=False,
            )

        operations = [preview for preview in previews if not preview.skipped and preview.source_path != preview.target_path]
        if not operations:
            self.statistics.finish()
            return RenameResult(
                batch_id=batch_id,
                previews=previews,
                dry_run=False,
                applied=True,
                rolled_back=False,
            )

        temp_pairs: list[tuple[Path, RenamePreview]] = []
        finalized: list[RenamePreview] = []

        try:
            for index, preview in enumerate(operations, start=1):
                source = preview.source_path
                if not source.exists():
                    raise RenameApplyError(f"Source file does not exist: {source}")

                temp = source.with_name(f".ailm_rename_tmp_{batch_id}_{index}{source.suffix}")
                while temp.exists():
                    temp = source.with_name(f".ailm_rename_tmp_{batch_id}_{index}_{uuid4().hex[:6]}{source.suffix}")

                source.rename(temp)
                temp_pairs.append((temp, preview))

            for temp, preview in temp_pairs:
                preview.target_path.parent.mkdir(parents=True, exist_ok=True)
                temp.rename(preview.target_path)
                self.repository.update_image_path(image_id=preview.image_id, new_path=preview.target_path)
                finalized.append(preview)
                self.statistics.increment_renamed()

            self._last_batch = RenameBatch(
                batch_id=batch_id,
                entries=[
                    RenameBatchEntry(
                        image_id=preview.image_id,
                        source_path=preview.source_path,
                        target_path=preview.target_path,
                    )
                    for preview in finalized
                ],
                applied_at=datetime.now(timezone.utc),
            )

            return RenameResult(
                batch_id=batch_id,
                previews=previews,
                dry_run=False,
                applied=True,
                rolled_back=False,
            )
        except Exception as exc:
            self.statistics.increment_failed()
            self._best_effort_restore(temp_pairs=temp_pairs, finalized=finalized)
            if isinstance(exc, RenameApplyError):
                raise
            raise RenameApplyError(f"Failed to apply rename batch: {exc}") from exc
        finally:
            self.statistics.finish()

    def rollback_last_batch(self) -> RenameResult | None:
        """Rollback the most recently applied rename batch."""
        if self._last_batch is None:
            return None

        batch = self._last_batch
        previews: list[RenamePreview] = []

        try:
            for entry in reversed(batch.entries):
                if not entry.target_path.exists():
                    raise RenameRollbackError(f"Cannot rollback missing target: {entry.target_path}")

                entry.source_path.parent.mkdir(parents=True, exist_ok=True)
                entry.target_path.rename(entry.source_path)
                self.repository.update_image_path(image_id=entry.image_id, new_path=entry.source_path)
                self.statistics.increment_rolled_back()

                previews.append(
                    RenamePreview(
                        image_id=entry.image_id,
                        source_path=entry.target_path,
                        target_path=entry.source_path,
                        sequence=0,
                        conflicted=False,
                        skipped=False,
                    )
                )
        except Exception as exc:
            self.statistics.increment_failed()
            if isinstance(exc, RenameRollbackError):
                raise
            raise RenameRollbackError(f"Failed to rollback batch {batch.batch_id}: {exc}") from exc

        self._last_batch = None
        previews.reverse()
        return RenameResult(
            batch_id=batch.batch_id,
            previews=previews,
            dry_run=False,
            applied=False,
            rolled_back=True,
        )

    def _build_previews(self, paths: Iterable[Path | str], *, rule: RenameRule | None) -> list[RenamePreview]:
        active_rule = rule or self.rule
        template = RenameTemplate(active_rule.template)

        previews: list[RenamePreview] = []
        reserved_targets: set[Path] = set()
        normalized_paths = sorted(Path(path).resolve() for path in paths)

        for sequence, source_path in enumerate(normalized_paths, start=1):
            self.statistics.increment_processed()
            context = self.repository.build_context(source_path)
            if context is None:
                self.statistics.increment_skipped()
                preview = RenamePreview(
                    image_id=0,
                    source_path=source_path,
                    target_path=source_path,
                    sequence=sequence,
                    skipped=True,
                    reason="Image not found in repository",
                )
                previews.append(preview)
                continue

            expanded_stem = template.expand(context, active_rule, sequence=sequence)
            candidate_name = build_safe_filename(
                expanded_stem,
                context.extension,
                max_stem_length=active_rule.max_stem_length,
            )

            candidate_path = source_path.with_name(candidate_name)
            resolved_path, conflicted = self._resolve_conflict(
                source_path=source_path,
                candidate_path=candidate_path,
                reserved_targets=reserved_targets,
                max_stem_length=active_rule.max_stem_length,
            )

            reserved_targets.add(resolved_path)
            preview = RenamePreview(
                image_id=context.image_id,
                source_path=source_path,
                target_path=resolved_path,
                sequence=sequence,
                conflicted=conflicted,
                skipped=False,
            )
            previews.append(preview)
            self.statistics.increment_previewed()
            if conflicted:
                self.statistics.increment_conflicts_resolved()

        return previews

    def _resolve_conflict(
        self,
        *,
        source_path: Path,
        candidate_path: Path,
        reserved_targets: set[Path],
        max_stem_length: int,
    ) -> tuple[Path, bool]:
        candidate = candidate_path
        conflicted = False
        counter = 1

        while self._is_conflict(source_path=source_path, candidate_path=candidate, reserved_targets=reserved_targets):
            conflicted = True
            numbered_stem = build_safe_filename(
                f"{candidate_path.stem}_{counter:03d}",
                "",
                max_stem_length=max_stem_length,
            )
            candidate = candidate_path.with_name(f"{numbered_stem}{candidate_path.suffix}")
            counter += 1

        return candidate, conflicted

    @staticmethod
    def _is_conflict(*, source_path: Path, candidate_path: Path, reserved_targets: set[Path]) -> bool:
        if candidate_path in reserved_targets:
            return True
        if candidate_path == source_path:
            return False
        return candidate_path.exists()

    def _best_effort_restore(
        self,
        *,
        temp_pairs: list[tuple[Path, RenamePreview]],
        finalized: list[RenamePreview],
    ) -> None:
        for preview in reversed(finalized):
            if preview.target_path.exists() and not preview.source_path.exists():
                try:
                    preview.target_path.rename(preview.source_path)
                    self.repository.update_image_path(image_id=preview.image_id, new_path=preview.source_path)
                except Exception:
                    pass

        for temp, preview in reversed(temp_pairs):
            if temp.exists() and not preview.source_path.exists():
                try:
                    temp.rename(preview.source_path)
                except Exception:
                    pass
