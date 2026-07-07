from __future__ import annotations

from engine.library_integrity.integrity_models import (
    IntegrityCheckName,
    IntegrityCheckResult,
    IntegrityIssue,
    IntegrityReport,
    IntegritySeverity,
    IntegritySummary,
)


class IntegrityBuilder:
    """Builds typed integrity report structures from raw check results."""

    def build_check_result(
        self,
        *,
        check_name: IntegrityCheckName,
        issues: list[IntegrityIssue],
        duration_seconds: float,
    ) -> IntegrityCheckResult:
        return IntegrityCheckResult(
            check_name=check_name,
            passed=len(issues) == 0,
            duration_seconds=max(0.0, duration_seconds),
            issues=list(issues),
        )

    def build_summary(self, check_results: list[IntegrityCheckResult]) -> IntegritySummary:
        warnings = 0
        errors = 0
        critical_errors = 0
        for result in check_results:
            for issue in result.issues:
                if issue.severity is IntegritySeverity.WARNING:
                    warnings += 1
                elif issue.severity is IntegritySeverity.ERROR:
                    errors += 1
                elif issue.severity is IntegritySeverity.CRITICAL:
                    critical_errors += 1

        failed = sum(1 for item in check_results if not item.passed)
        passed = len(check_results) - failed
        issues_found = warnings + errors + critical_errors
        return IntegritySummary(
            checks_performed=len(check_results),
            passed_checks=passed,
            failed_checks=failed,
            issues_found=issues_found,
            warnings=warnings,
            errors=errors,
            critical_errors=critical_errors,
        )

    def build_report(
        self,
        *,
        check_results: list[IntegrityCheckResult],
        execution_time_seconds: float,
        cancelled: bool = False,
        resumed: bool = False,
    ) -> IntegrityReport:
        passed_checks = [item.check_name for item in check_results if item.passed]
        failed_checks = [item.check_name for item in check_results if not item.passed]

        warnings: list[IntegrityIssue] = []
        errors: list[IntegrityIssue] = []
        for result in check_results:
            for issue in result.issues:
                if issue.severity is IntegritySeverity.WARNING:
                    warnings.append(issue)
                elif issue.severity in {IntegritySeverity.ERROR, IntegritySeverity.CRITICAL}:
                    errors.append(issue)

        return IntegrityReport(
            check_results=list(check_results),
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            warnings=warnings,
            errors=errors,
            execution_time_seconds=max(0.0, execution_time_seconds),
            summary=self.build_summary(check_results),
            cancelled=cancelled,
            resumed=resumed,
        )
