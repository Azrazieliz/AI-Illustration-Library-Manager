from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from engine.logging import get_logger
from engine.metadata.metadata_events import (
    MetadataCompleted,
    MetadataExtracted,
    MetadataFailed,
    MetadataStarted,
)
from engine.metadata.metadata_exceptions import (
    CorruptedImageError,
    MetadataExtractionError,
    UnsupportedImageFormatError,
)
from engine.metadata.metadata_extractor import MetadataExtractor
from engine.metadata.metadata_models import (
    ExtractedMetadata,
    MetadataCheckpoint,
    MetadataResult,
)
from engine.metadata.metadata_statistics import MetadataStatistics
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository


class MetadataWorker:
    """Performs parallel metadata extraction with crash recovery.

    Each worker thread gets its own repository instances to avoid
    SQLAlchemy session sharing issues.
    """

    def __init__(
        self,
        *,
        image_repository: ImageRepository | None = None,
        metadata_repository: MetadataRepository | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.image_repository = image_repository or ImageRepository()
        self.metadata_repository = metadata_repository or MetadataRepository()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = MetadataStatistics()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: MetadataCheckpoint | None = None,
    ) -> list[MetadataResult]:
        """Process metadata extraction for multiple paths with parallel execution.

        Files that are skipped (checkpoint) are not included in the returned
        list but are counted in ``statistics.processed``.
        """
        self.statistics = MetadataStatistics()
        self.statistics.start()
        results: list[MetadataResult] = []
        paths_list = [str(Path(p).resolve()) for p in paths]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_one, path): path
                for path in paths_list
                if checkpoint is None or not checkpoint.is_processed(path)
            }

            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)
                    if result.metadata.mime_type:
                        self.statistics.extracted += 1

                    # Update Image record with dimension info if available
                    if result.metadata.width and result.metadata.height:
                        img_record = self.image_repository.get_image(result.image_id)
                        if img_record:
                            self.image_repository.update_image(
                                img_record,
                                width=result.metadata.width,
                                height=result.metadata.height,
                            )

                    if checkpoint is not None:
                        checkpoint.add_processed(result.path)

        self.statistics.finish()
        return results

    def process_path(
        self,
        path: Path | str,
        *,
        checkpoint: MetadataCheckpoint | None = None,
    ) -> MetadataResult | None:
        """Extract metadata from a single path."""
        resolved = Path(path).resolve()

        if checkpoint is not None and checkpoint.is_processed(str(resolved)):
            return None

        return self._process_one(str(resolved))

    # ------------------------------------------------------------------ #
    # Internal helpers (thread-safe)                                      #
    # ------------------------------------------------------------------ #

    def _process_one(self, path: str) -> MetadataResult | None:
        """Process a single path in a worker thread.

        Each invocation creates fresh per-thread repositories to avoid
        SQLAlchemy session sharing issues.
        """
        resolved_path = Path(path)

        # Per-thread repository instances
        image_repo = ImageRepository()
        metadata_repo = MetadataRepository()

        self.statistics.processed += 1

        try:
            self._emit(MetadataStarted(path=resolved_path))

            # Extract metadata from file
            try:
                extracted_metadata = MetadataExtractor.extract(resolved_path)
            except UnsupportedImageFormatError:
                self.statistics.unsupported += 1
                self._emit(
                    MetadataFailed(
                        path=resolved_path,
                        error="Unsupported image format",
                    )
                )
                return None
            except CorruptedImageError:
                self.statistics.corrupted += 1
                self._emit(
                    MetadataFailed(
                        path=resolved_path,
                        error="Image is corrupted or unreadable",
                    )
                )
                return None
            except MetadataExtractionError as e:
                self.statistics.failed += 1
                self._emit(
                    MetadataFailed(
                        path=resolved_path,
                        error=str(e),
                    )
                )
                return None

            # Look up image record
            image = image_repo.get_by_path(str(resolved_path))
            if image is None:
                self.statistics.failed += 1
                self._emit(
                    MetadataFailed(
                        path=resolved_path,
                        error="No image record found",
                    )
                )
                return None

            # Create or update metadata record
            existing = metadata_repo.get_by_image_id(image.id)
            if existing:
                metadata_repo.update_metadata_record(
                    existing,
                    aspect_ratio=extracted_metadata.aspect_ratio,
                    orientation=extracted_metadata.orientation,
                    mime_type=extracted_metadata.mime_type,
                    color_mode=extracted_metadata.color_mode,
                    bit_depth=extracted_metadata.bit_depth,
                    dpi=extracted_metadata.dpi,
                    has_icc_profile=extracted_metadata.has_icc_profile,
                    is_animated=extracted_metadata.is_animated,
                    frame_count=extracted_metadata.frame_count,
                    exif_data=extracted_metadata.exif_data,
                )
            else:
                metadata_repo.create_metadata_record(
                    image_id=image.id,
                    aspect_ratio=extracted_metadata.aspect_ratio,
                    orientation=extracted_metadata.orientation,
                    mime_type=extracted_metadata.mime_type,
                    color_mode=extracted_metadata.color_mode,
                    bit_depth=extracted_metadata.bit_depth,
                    dpi=extracted_metadata.dpi,
                    has_icc_profile=extracted_metadata.has_icc_profile,
                    is_animated=extracted_metadata.is_animated,
                    frame_count=extracted_metadata.frame_count,
                    exif_data=extracted_metadata.exif_data,
                )

            self._emit(
                MetadataExtracted(
                    path=resolved_path,
                    mime_type=extracted_metadata.mime_type,
                    width=extracted_metadata.width,
                    height=extracted_metadata.height,
                )
            )

            result = MetadataResult(
                image_id=image.id,
                path=resolved_path,
                metadata=extracted_metadata,
            )
            return result

        except Exception as e:
            self.statistics.failed += 1
            self._emit(
                MetadataFailed(
                    path=resolved_path,
                    error=f"Unexpected error: {e}",
                )
            )
            return None

    def _emit(self, event: object) -> None:
        """Emit an event to registered listeners."""
        if self.callback is not None:
            self.callback(event)
