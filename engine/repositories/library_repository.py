from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from engine.collections.collection_models import CollectionRecord
from engine.database.models.embedding import Embedding
from engine.database.models.hash import HashModel
from engine.database.models.metadata import MetadataRecord
from engine.database.models.thumbnail import ThumbnailRecord
from engine.database.models.duplicate import DuplicateRecord
from engine.database.models.image import Image
from engine.library.library_models import (
    LibraryDuplicateStatistics,
    LibraryFolderStatistic,
    LibraryIssue,
    LibraryScanHistoryEntry,
    LibraryStorageStatistic,
    LibraryTaxonomyStatistic,
)
from engine.repositories.character_repository import CharacterRepository
from engine.repositories.collection_repository import CollectionRepository
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.series_repository import SeriesRepository
from engine.repositories.tag_repository import TagRepository


class LibraryRepository:
    """Aggregates cross-domain library statistics using existing repositories."""

    def __init__(self) -> None:
        self.image_repository = ImageRepository()
        self.duplicate_repository = DuplicateRepository()
        self.tag_repository = TagRepository()
        self.character_repository = CharacterRepository()
        self.series_repository = SeriesRepository()
        self.collection_repository = CollectionRepository()

    def list_images(self) -> list[Image]:
        return self.image_repository.list_images()

    def list_collections(self) -> list[CollectionRecord]:
        return self.collection_repository.list_collections()

    def detect_missing_files(self, images: list[Image]) -> list[LibraryIssue]:
        issues: list[LibraryIssue] = []
        for image in images:
            path = Path(image.current_path or image.original_path)
            if path.exists():
                continue
            issues.append(
                LibraryIssue(
                    kind="missing_file",
                    reference=f"image:{image.id}",
                    detail=str(path),
                )
            )
        return issues

    def detect_broken_references(self, collections: list[CollectionRecord], image_ids: set[int]) -> list[LibraryIssue]:
        issues: list[LibraryIssue] = []
        for collection in collections:
            for image_id in sorted(collection.image_ids):
                if image_id in image_ids:
                    continue
                issues.append(
                    LibraryIssue(
                        kind="broken_reference",
                        reference=f"collection:{collection.collection_id}",
                        detail=f"missing image_id={image_id}",
                    )
                )
        return issues

    def detect_orphan_records(self, image_ids: set[int]) -> list[LibraryIssue]:
        issues: list[LibraryIssue] = []
        session = self.image_repository.session

        for record in session.query(HashModel).all():
            if record.image_id not in image_ids:
                issues.append(
                    LibraryIssue(
                        kind="orphan_record",
                        reference=f"hash:{record.id}",
                        detail=f"image_id={record.image_id}",
                    )
                )

        for record in session.query(MetadataRecord).all():
            if record.image_id not in image_ids:
                issues.append(
                    LibraryIssue(
                        kind="orphan_record",
                        reference=f"metadata:{record.id}",
                        detail=f"image_id={record.image_id}",
                    )
                )

        for record in session.query(Embedding).all():
            if record.image_id not in image_ids:
                issues.append(
                    LibraryIssue(
                        kind="orphan_record",
                        reference=f"embedding:{record.id}",
                        detail=f"image_id={record.image_id}",
                    )
                )

        for record in session.query(ThumbnailRecord).all():
            if record.image_id not in image_ids:
                issues.append(
                    LibraryIssue(
                        kind="orphan_record",
                        reference=f"thumbnail:{record.id}",
                        detail=f"image_id={record.image_id}",
                    )
                )

        for record in session.query(DuplicateRecord).all():
            if record.image_a_id in image_ids and record.image_b_id in image_ids:
                continue
            issues.append(
                LibraryIssue(
                    kind="orphan_record",
                    reference=f"duplicate:{record.id}",
                    detail=f"pair=({record.image_a_id},{record.image_b_id})",
                )
            )

        return issues

    def detect_empty_collections(self, collections: list[CollectionRecord]) -> list[LibraryIssue]:
        issues: list[LibraryIssue] = []
        for collection in collections:
            if len(collection.image_ids) > 0:
                continue
            issues.append(
                LibraryIssue(
                    kind="empty_collection",
                    reference=f"collection:{collection.collection_id}",
                    detail=collection.name,
                )
            )
        return issues

    def duplicate_statistics(self) -> LibraryDuplicateStatistics:
        records = self.duplicate_repository.list_all_duplicates()
        pending = sum(1 for item in records if item.status == "pending")
        reviewed = sum(1 for item in records if item.status == "reviewed")
        rejected = sum(1 for item in records if item.status == "rejected")
        exact = sum(1 for item in records if item.match_type == "exact")
        perceptual = sum(1 for item in records if item.match_type == "perceptual")
        return LibraryDuplicateStatistics(
            total_pairs=len(records),
            pending=pending,
            reviewed=reviewed,
            rejected=rejected,
            exact=exact,
            perceptual=perceptual,
        )

    def tag_statistics(self) -> list[LibraryTaxonomyStatistic]:
        rows = [
            LibraryTaxonomyStatistic(name=tag.name, image_count=len(tag.images))
            for tag in self.tag_repository.list_tags()
            if len(tag.images) > 0
        ]
        rows.sort(key=lambda item: (-item.image_count, item.name.lower()))
        return rows

    def character_statistics(self) -> list[LibraryTaxonomyStatistic]:
        rows = [
            LibraryTaxonomyStatistic(name=character.name, image_count=len(character.images))
            for character in self.character_repository.list_characters()
            if len(character.images) > 0
        ]
        rows.sort(key=lambda item: (-item.image_count, item.name.lower()))
        return rows

    def series_statistics(self) -> list[LibraryTaxonomyStatistic]:
        rows = [
            LibraryTaxonomyStatistic(name=series.name, image_count=len(series.images))
            for series in self.series_repository.list_series()
            if len(series.images) > 0
        ]
        rows.sort(key=lambda item: (-item.image_count, item.name.lower()))
        return rows

    def storage_statistics(self, images: list[Image]) -> LibraryStorageStatistic:
        sizes: list[int] = [self._image_size(image) for image in images]
        total = sum(sizes)
        average = int(total / len(sizes)) if sizes else 0
        largest = max(sizes) if sizes else 0
        return LibraryStorageStatistic(total_bytes=total, average_bytes=average, largest_bytes=largest)

    def folder_statistics(self, images: list[Image]) -> list[LibraryFolderStatistic]:
        grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"image_count": 0, "total_bytes": 0, "missing_files": 0})

        for image in images:
            path = Path(image.current_path or image.original_path)
            folder = str(path.parent)
            grouped[folder]["image_count"] += 1
            grouped[folder]["total_bytes"] += self._image_size(image)
            if not path.exists():
                grouped[folder]["missing_files"] += 1

        rows = [
            LibraryFolderStatistic(
                folder_path=folder,
                image_count=values["image_count"],
                total_bytes=values["total_bytes"],
                missing_files=values["missing_files"],
            )
            for folder, values in grouped.items()
        ]
        rows.sort(key=lambda item: (-item.image_count, item.folder_path.lower()))
        return rows

    def scan_history(self, images: list[Image]) -> list[LibraryScanHistoryEntry]:
        grouped: dict[datetime, int] = defaultdict(int)

        for image in images:
            if image.scan_date is None:
                continue
            timestamp = self._normalize_timestamp(image.scan_date)
            bucket = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            grouped[bucket] += 1

        rows = [
            LibraryScanHistoryEntry(scanned_at=scanned_at, images_scanned=count)
            for scanned_at, count in grouped.items()
        ]
        rows.sort(key=lambda item: item.scanned_at, reverse=True)
        return rows

    def latest_scan_time(self, images: list[Image]) -> datetime | None:
        timestamps = [self._normalize_timestamp(image.scan_date) for image in images if image.scan_date is not None]
        if not timestamps:
            return None
        return max(timestamps)

    def _normalize_timestamp(self, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp

    def _image_size(self, image: Image) -> int:
        if image.filesize is not None and image.filesize >= 0:
            return image.filesize

        path = Path(image.current_path or image.original_path)
        if not path.exists():
            return 0
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
