from __future__ import annotations

from engine.library.library_models import (
    LibraryCleanupRecommendation,
    LibraryHealthReport,
    LibraryHealthStatus,
    LibrarySummary,
    RecommendationSeverity,
)


class LibraryBuilder:
    """Builds derived summary/health/recommendation views for library analysis."""

    def build_health(self, summary: LibrarySummary) -> LibraryHealthReport:
        score = 100.0
        score -= min(35.0, float(summary.missing_files) * 4.0)
        score -= min(30.0, float(summary.broken_references) * 6.0)
        score -= min(20.0, float(summary.orphan_records) * 5.0)
        score -= min(10.0, float(summary.empty_collections) * 2.0)
        score -= min(10.0, float(summary.duplicate_pairs) * 1.0)
        score = max(0.0, round(score, 2))

        issues: list[str] = []
        if summary.missing_files > 0:
            issues.append(f"{summary.missing_files} missing files")
        if summary.broken_references > 0:
            issues.append(f"{summary.broken_references} broken references")
        if summary.orphan_records > 0:
            issues.append(f"{summary.orphan_records} orphan records")
        if summary.empty_collections > 0:
            issues.append(f"{summary.empty_collections} empty collections")
        if summary.duplicate_pairs > 0:
            issues.append(f"{summary.duplicate_pairs} duplicate pairs")

        if score >= 90.0:
            status = LibraryHealthStatus.HEALTHY
        elif score >= 70.0:
            status = LibraryHealthStatus.WARNING
        else:
            status = LibraryHealthStatus.CRITICAL

        return LibraryHealthReport(score=score, status=status, issues=issues)

    def build_cleanup_recommendations(self, summary: LibrarySummary) -> list[LibraryCleanupRecommendation]:
        recommendations: list[LibraryCleanupRecommendation] = []

        if summary.missing_files > 0:
            recommendations.append(
                LibraryCleanupRecommendation(
                    code="restore-missing-files",
                    severity=RecommendationSeverity.HIGH,
                    message="Verify disk locations and remove stale image records for missing files.",
                    affected_count=summary.missing_files,
                )
            )

        if summary.broken_references > 0:
            recommendations.append(
                LibraryCleanupRecommendation(
                    code="repair-broken-references",
                    severity=RecommendationSeverity.HIGH,
                    message="Repair collection memberships that reference non-existent images.",
                    affected_count=summary.broken_references,
                )
            )

        if summary.orphan_records > 0:
            recommendations.append(
                LibraryCleanupRecommendation(
                    code="cleanup-orphan-records",
                    severity=RecommendationSeverity.MEDIUM,
                    message="Remove records whose referenced images are no longer present.",
                    affected_count=summary.orphan_records,
                )
            )

        if summary.empty_collections > 0:
            recommendations.append(
                LibraryCleanupRecommendation(
                    code="review-empty-collections",
                    severity=RecommendationSeverity.LOW,
                    message="Archive or delete empty collections to keep navigation clean.",
                    affected_count=summary.empty_collections,
                )
            )

        if summary.duplicate_pairs > 0:
            recommendations.append(
                LibraryCleanupRecommendation(
                    code="resolve-duplicates",
                    severity=RecommendationSeverity.MEDIUM,
                    message="Review duplicate pairs and consolidate confirmed duplicates.",
                    affected_count=summary.duplicate_pairs,
                )
            )

        return recommendations
