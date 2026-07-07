from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IntegrityStatistics:
    total_scans: int = 0
    checks_performed: int = 0
    issues_found: int = 0
    warnings: int = 0
    errors: int = 0
    critical_errors: int = 0
    total_scan_duration_seconds: float = 0.0

    @property
    def average_scan_duration_seconds(self) -> float:
        if self.total_scans <= 0:
            return 0.0
        return round(self.total_scan_duration_seconds / float(self.total_scans), 6)

    def record_scan(self, *, duration_seconds: float, checks_performed: int, warnings: int, errors: int, critical_errors: int) -> None:
        self.total_scans += 1
        self.checks_performed += checks_performed
        self.warnings += warnings
        self.errors += errors
        self.critical_errors += critical_errors
        self.issues_found += warnings + errors + critical_errors
        self.total_scan_duration_seconds += max(0.0, duration_seconds)
