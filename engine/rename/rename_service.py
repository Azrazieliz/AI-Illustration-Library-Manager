from __future__ import annotations

from pathlib import Path

from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.rename.rename_engine import RenameEngine
from engine.rename.rename_models import RenameResult, RenameRule


class RenameService:
    """Service facade connecting rename engine operations to pipeline jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: RenameEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or RenameEngine(callback=self._handle_event)

    def preview_rename(
        self,
        paths: list[Path | str],
        *,
        rule: RenameRule | None = None,
    ) -> list:
        return self.engine.preview_rename(paths, rule=rule)

    def apply_rename(
        self,
        paths: list[Path | str],
        *,
        rule: RenameRule | None = None,
        dry_run: bool = False,
    ) -> RenameResult:
        return self.engine.apply_rename(paths, rule=rule, dry_run=dry_run)

    def rollback_last_batch(self) -> RenameResult | None:
        return self.engine.rollback_last_batch()

    def process_rename_job(
        self,
        job: PipelineJob,
        *,
        rule: RenameRule | None = None,
        dry_run: bool = False,
    ) -> RenameResult | None:
        if not job.source_path:
            return None

        stage = (job.metadata or {}).get("stage")
        if stage not in {None, "rename"}:
            return None

        return self.engine.apply_rename([Path(job.source_path)], rule=rule, dry_run=dry_run)

    def process_rename_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        rule: RenameRule | None = None,
        dry_run: bool = False,
    ) -> list[RenameResult]:
        results: list[RenameResult] = []
        for job in jobs:
            result = self.process_rename_job(job, rule=rule, dry_run=dry_run)
            if result is not None:
                results.append(result)
        return results

    def _handle_event(self, event: object) -> None:
        return None
