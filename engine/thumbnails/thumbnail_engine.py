from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from engine.config import settings
from engine.thumbnails.thumbnail_cache import ThumbnailCache, make_cache_key
from engine.thumbnails.thumbnail_events import (
    ThumbnailCacheHit,
    ThumbnailCompleted,
    ThumbnailFailed,
    ThumbnailGenerated,
    ThumbnailStarted,
)
from engine.thumbnails.thumbnail_exceptions import ThumbnailEngineError
from engine.thumbnails.thumbnail_generator import ThumbnailGenerator
from engine.thumbnails.thumbnail_models import (
    DEFAULT_SIZES,
    ThumbnailCheckpoint,
    ThumbnailFormat,
    ThumbnailResult,
    ThumbnailSpec,
)
from engine.thumbnails.thumbnail_statistics import ThumbnailStatistics
from engine.repositories.image_repository import ImageRepository
from engine.repositories.thumbnail_repository import ThumbnailRepository


class ThumbnailEngine:
    """Generates and caches thumbnails for indexed image files.

    Architecture
    ------------
    * Images are processed in parallel using a ``ThreadPoolExecutor``.
    * Each image is loaded once and all requested sizes are produced before
      the next image starts (constant-memory per task).
    * A persistent cache prevents regenerating thumbnails for unchanged files.
    * Corrupted or unreadable images are logged and skipped gracefully.

    Crash Recovery
    --------------
    An optional :class:`ThumbnailCheckpoint` records successfully processed
    paths.  On restart, those paths are skipped so no work is repeated.
    Additionally, the cache layer validates on-disk files before skipping,
    so partially written thumbnails are always regenerated.
    """

    _DEFAULT_SPECS: list[ThumbnailSpec] = [
        ThumbnailSpec(size=s, format=ThumbnailFormat.WEBP) for s in DEFAULT_SIZES
    ]

    def __init__(
        self,
        *,
        image_repository: ImageRepository | None = None,
        thumbnail_repository: ThumbnailRepository | None = None,
        callback: Callable[[object], None] | None = None,
        specs: list[ThumbnailSpec] | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.image_repository = image_repository or ImageRepository()
        self.thumbnail_repository = thumbnail_repository or ThumbnailRepository()
        self.callback = callback
        self.specs: list[ThumbnailSpec] = specs or self._DEFAULT_SPECS
        self.max_workers: int = max_workers or settings.max_background_workers
        self.statistics = ThumbnailStatistics()

        cache_dir = Path(settings.workspace) / settings.thumbnail_directory
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = ThumbnailCache(cache_dir, self.thumbnail_repository)
        self._generator = ThumbnailGenerator()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: ThumbnailCheckpoint | None = None,
    ) -> list[ThumbnailResult]:
        """Generate thumbnails for all *paths* in parallel.

        Already-cached images are served from disk without Pillow I/O.
        Corrupted images produce a :class:`ThumbnailFailed` event and are
        counted in ``statistics.failed`` but do not interrupt the run.
        """
        self.statistics = ThumbnailStatistics()
        self.statistics.start()

        path_list = [Path(p).resolve() for p in paths]

        # Filter paths that the checkpoint has already processed
        to_process: list[Path] = []
        for p in path_list:
            if checkpoint is not None and str(p) in checkpoint.processed_paths:
                # Already done – count as cached since thumbnails must be on disk
                self.statistics.cached += 1
                self.statistics.processed += 1
            else:
                to_process.append(p)

        results: list[ThumbnailResult] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_path = {
                executor.submit(self._process_one, p): p for p in to_process
            }
            for future in as_completed(future_to_path):
                p = future_to_path[future]
                try:
                    result = future.result()
                    if result is not None:
                        results.append(result)
                        if checkpoint is not None:
                            checkpoint.processed_paths.add(str(p))
                        # Update statistics in the main thread (thread-safe)
                        if result.from_cache:
                            self.statistics.cached += 1
                        else:
                            self.statistics.generated += 1
                        self.statistics.processed += 1
                except Exception as exc:
                    self.statistics.failed += 1
                    self.statistics.processed += 1
                    self._emit(ThumbnailFailed(source_path=str(p), error=str(exc)))

        self.statistics.complete()
        self._emit(
            ThumbnailCompleted(
                total=self.statistics.processed,
                generated=self.statistics.generated,
                cached=self.statistics.cached,
                failed=self.statistics.failed,
            )
        )
        return results

    def process_path(
        self,
        path: Path | str,
        *,
        checkpoint: ThumbnailCheckpoint | None = None,
    ) -> ThumbnailResult | None:
        """Convenience wrapper to process a single *path*."""
        results = self.process_paths([path], checkpoint=checkpoint)
        return results[0] if results else None

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _process_one(self, path: Path) -> ThumbnailResult | None:
        # Each thread gets its own repository instances so SQLAlchemy sessions
        # are never shared across threads.
        image_repo = ImageRepository()
        thumb_repo = ThumbnailRepository()
        from engine.thumbnails.thumbnail_cache import ThumbnailCache
        cache = ThumbnailCache(self._cache.cache_dir, thumb_repo)

        self._emit(ThumbnailStarted(source_path=str(path)))

        if not path.exists():
            raise ThumbnailEngineError(f"File not found: {path}")

        image = image_repo.get_by_path(str(path))
        stat = path.stat()
        cache_key = make_cache_key(path, stat.st_size, stat.st_mtime)

        # --- Cache hit ---
        if image is not None and cache.all_valid(image.id, cache_key, self.specs):
            cached = cache.load_cached(image.id, cache_key, self.specs)
            self._emit(
                ThumbnailCacheHit(
                    source_path=str(path),
                    sizes=[t.spec.size for t in cached],
                )
            )
            return ThumbnailResult(
                source_path=str(path),
                image_id=image.id if image else -1,
                thumbnails=cached,
                from_cache=True,
            )

        # --- Generate ---
        thumbnails = self._generator.generate(
            source_path=path,
            specs=self.specs,
            cache_dir=cache.cache_dir,
            cache_key=cache_key,
        )

        # Persist metadata and update image record
        for thumb in thumbnails:
            if image is not None:
                cache.persist(image.id, thumb)

        if image is not None:
            image_repo.mark_thumbnail_created(image)
            if image.width is None or image.height is None:
                first_thumb = thumbnails[0] if thumbnails else None
                if first_thumb:
                    image.width = first_thumb.width
                    image.height = first_thumb.height
                    image_repo.commit()

        self._emit(
            ThumbnailGenerated(
                source_path=str(path),
                sizes=[t.spec.size for t in thumbnails],
                file_paths=[str(t.file_path) for t in thumbnails],
            )
        )
        return ThumbnailResult(
            source_path=str(path),
            image_id=image.id if image else -1,
            thumbnails=thumbnails,
            from_cache=False,
        )

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
