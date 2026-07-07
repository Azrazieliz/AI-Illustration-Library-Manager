from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MaintenanceStatistics:
    maintenance_runs: int = 0
    repaired_items: int = 0
    failed_repairs: int = 0
    skipped_repairs: int = 0
    cancelled_jobs: int = 0
    resumed_jobs: int = 0
    total_runtime_seconds: float = 0.0

    @property
    def average_runtime_seconds(self) -> float:
        if self.maintenance_runs <= 0:
            return 0.0
        return round(self.total_runtime_seconds / float(self.maintenance_runs), 6)

    def record_run(
        self,
        *,
        repaired_items: int,
        failed_repairs: int,
        skipped_repairs: int,
        runtime_seconds: float,
        cancelled: bool,
        resumed: bool,
    ) -> None:
        self.maintenance_runs += 1
        self.repaired_items += max(0, repaired_items)
        self.failed_repairs += max(0, failed_repairs)
        self.skipped_repairs += max(0, skipped_repairs)
        self.total_runtime_seconds += max(0.0, runtime_seconds)
        if cancelled:
            self.cancelled_jobs += 1
        if resumed:
            self.resumed_jobs += 1
