from __future__ import annotations

from pathlib import Path

from engine.organizer.organizer_engine import OrganizerEngine
from engine.organizer.organizer_models import OrganizationPlan, OrganizationResult, OrganizationRule
from engine.pipeline import PipelineJob, QueueManager, QueueType


class OrganizerService:
    """Service facade connecting organizer engine to stage-marked pipeline jobs."""

    def __init__(
        self,
        *,
        queue_manager: QueueManager | None = None,
        engine: OrganizerEngine | None = None,
    ) -> None:
        self.queue_manager = queue_manager or QueueManager()
        self.engine = engine or OrganizerEngine(callback=self._handle_event)

    def preview_organize(
        self,
        paths: list[Path | str],
        *,
        rules: list[OrganizationRule] | None = None,
    ) -> OrganizationPlan:
        return self.engine.preview_organize(paths, rules=rules)

    def apply_organize(
        self,
        paths: list[Path | str],
        *,
        rules: list[OrganizationRule] | None = None,
        dry_run: bool = False,
    ) -> OrganizationResult:
        return self.engine.apply_organize(paths, rules=rules, dry_run=dry_run)

    def rollback_last_batch(self) -> OrganizationResult | None:
        return self.engine.rollback_last_batch()

    def process_organizer_job(
        self,
        job: PipelineJob,
        *,
        rules: list[OrganizationRule] | None = None,
        dry_run: bool = False,
    ) -> OrganizationResult | None:
        if not job.source_path:
            return None

        stage = (job.metadata or {}).get("stage")
        if stage != "organizer":
            return None

        return self.engine.apply_organize([Path(job.source_path)], rules=rules, dry_run=dry_run)

    def process_organizer_jobs(
        self,
        jobs: list[PipelineJob],
        *,
        rules: list[OrganizationRule] | None = None,
        dry_run: bool = False,
    ) -> list[OrganizationResult]:
        results: list[OrganizationResult] = []
        for job in jobs:
            result = self.process_organizer_job(job, rules=rules, dry_run=dry_run)
            if result is not None:
                results.append(result)
        return results

    def _handle_event(self, event: object) -> None:
        return None
