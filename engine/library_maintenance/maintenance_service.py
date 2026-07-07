from __future__ import annotations

from engine.library_maintenance.maintenance_engine import LibraryMaintenanceEngine
from engine.library_maintenance.maintenance_models import MaintenanceReport, MaintenanceTaskType


class LibraryMaintenanceService:
    """Service facade for library maintenance operations."""

    def __init__(self, *, engine: LibraryMaintenanceEngine | None = None) -> None:
        self.engine = engine or LibraryMaintenanceEngine(callback=self._handle_event)

    def run_full_maintenance(self, *, preview: bool = False, dry_run: bool = False, job_id: str | None = None, resumed: bool = False) -> MaintenanceReport:
        return self.engine.run_full_maintenance(preview=preview, dry_run=dry_run, job_id=job_id, resumed=resumed)

    def run_selected_tasks(self, tasks: list[MaintenanceTaskType], *, preview: bool = False, dry_run: bool = False, job_id: str | None = None, resumed: bool = False) -> MaintenanceReport:
        return self.engine.run_selected_tasks(tasks, preview=preview, dry_run=dry_run, job_id=job_id, resumed=resumed)

    def preview_repairs(self, tasks: list[MaintenanceTaskType] | None = None) -> MaintenanceReport:
        return self.engine.preview_repairs(tasks)

    def cancel_job(self, job_id: str) -> None:
        self.engine.cancel_job(job_id)

    def resume_job(self, job_id: str) -> MaintenanceReport:
        return self.engine.resume_job(job_id)

    def rollback_job(self, job_id: str) -> int:
        return self.engine.rollback_job(job_id)

    def _handle_event(self, event: object) -> None:
        return None
