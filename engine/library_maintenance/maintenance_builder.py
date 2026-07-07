from __future__ import annotations

from engine.library_maintenance.maintenance_models import MaintenanceJob, MaintenanceReport, MaintenanceResult, MaintenanceSummary, MaintenanceWarning
from engine.library_maintenance.maintenance_statistics import MaintenanceStatistics


class MaintenanceBuilder:
    """Build report and summary payloads for maintenance runs."""

    def build_summary(self, results: list[MaintenanceResult]) -> MaintenanceSummary:
        repaired = sum(item.repaired_items for item in results)
        skipped = sum(item.skipped_items for item in results)
        failed = sum(item.failed_items for item in results)
        warnings = sum(len(item.warnings) for item in results)
        return MaintenanceSummary(
            total_tasks=len(results),
            repaired_items=repaired,
            skipped_items=skipped,
            failed_items=failed,
            warnings=warnings,
        )

    def build_report(
        self,
        *,
        job: MaintenanceJob,
        results: list[MaintenanceResult],
        execution_time_seconds: float,
        dry_run: bool,
        preview: bool,
        resumed: bool,
        cancelled: bool,
    ) -> MaintenanceReport:
        return MaintenanceReport(
            job=job,
            results=list(results),
            summary=self.build_summary(results),
            execution_time_seconds=max(0.0, execution_time_seconds),
            dry_run=dry_run,
            preview=preview,
            resumed=resumed,
            cancelled=cancelled,
        )

    def build_statistics(
        self,
        *,
        existing: MaintenanceStatistics,
        report: MaintenanceReport,
    ) -> MaintenanceStatistics:
        existing.record_run(
            repaired_items=report.summary.repaired_items,
            failed_repairs=report.summary.failed_items,
            skipped_repairs=report.summary.skipped_items,
            runtime_seconds=report.execution_time_seconds,
            cancelled=report.cancelled,
            resumed=report.resumed,
        )
        return existing
