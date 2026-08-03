from __future__ import annotations

from engine.library.library_builder import LibraryBuilder
from engine.library.library_models import (
    LibraryAnalysisReport,
    LibraryHealthReport,
    LibraryStatisticsReport,
    LibrarySummary,
)
from engine.repositories.library_repository import LibraryRepository


class LibraryEngine:
    """Builds high-level operational insights for the full illustration library."""

    def __init__(
        self,
        *,
        repository: LibraryRepository | None = None,
        builder: LibraryBuilder | None = None,
    ) -> None:
        self.repository = repository or LibraryRepository()
        self.builder = builder or LibraryBuilder()

    def summary(self) -> LibrarySummary:
        images = self.repository.list_images()
        collections = self.repository.list_collections()
        image_ids = {image.id for image in images}

        missing_files = self.repository.detect_missing_files(images)
        broken_references = self.repository.detect_broken_references(collections, image_ids)
        orphan_records = self.repository.detect_orphan_records(image_ids)
        empty_collections = self.repository.detect_empty_collections(collections)
        duplicate_statistics = self.repository.duplicate_statistics()
        storage_statistics = self.repository.storage_statistics(images)

        return LibrarySummary(
            total_images=len(images),
            total_collections=len(collections),
            total_tags=len(self.repository.tag_repository.list_tags()),
            total_characters=len(self.repository.character_repository.list_characters()),
            total_series=len(self.repository.series_repository.list_series()),
            total_storage_bytes=storage_statistics.total_bytes,
            missing_files=len(missing_files),
            broken_references=len(broken_references),
            orphan_records=len(orphan_records),
            empty_collections=len(empty_collections),
            duplicate_pairs=duplicate_statistics.total_pairs,
            last_scan_at=self.repository.latest_scan_time(images),
        )

    def list_images(self):
        return self.repository.list_images()

    def statistics(self) -> LibraryStatisticsReport:
        images = self.repository.list_images()
        return LibraryStatisticsReport(
            duplicate_statistics=self.repository.duplicate_statistics(),
            tag_statistics=self.repository.tag_statistics(),
            character_statistics=self.repository.character_statistics(),
            series_statistics=self.repository.series_statistics(),
            storage_statistics=self.repository.storage_statistics(images),
            folder_statistics=self.repository.folder_statistics(images),
            scan_history=self.repository.scan_history(images),
        )

    def health(self) -> LibraryHealthReport:
        return self.builder.build_health(self.summary())

    def analyze(self) -> LibraryAnalysisReport:
        images = self.repository.list_images()
        collections = self.repository.list_collections()
        image_ids = {image.id for image in images}

        missing_files = self.repository.detect_missing_files(images)
        broken_references = self.repository.detect_broken_references(collections, image_ids)
        orphan_records = self.repository.detect_orphan_records(image_ids)
        empty_collections = self.repository.detect_empty_collections(collections)

        summary = self.summary()
        statistics = self.statistics()
        health = self.builder.build_health(summary)
        recommendations = self.builder.build_cleanup_recommendations(summary)

        return LibraryAnalysisReport(
            summary=summary,
            health=health,
            statistics=statistics,
            missing_files=missing_files,
            broken_references=broken_references,
            orphan_records=orphan_records,
            empty_collections=empty_collections,
            cleanup_recommendations=recommendations,
        )
