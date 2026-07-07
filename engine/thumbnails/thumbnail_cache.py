from __future__ import annotations

import hashlib
from pathlib import Path

from engine.thumbnails.thumbnail_models import GeneratedThumbnail, ThumbnailFormat, ThumbnailSpec
from engine.repositories.thumbnail_repository import ThumbnailRepository


def make_cache_key(source_path: Path, file_size: int, mtime: float) -> str:
    """Derive a 32-character cache key from source identity.

    The key encodes the absolute path, byte-size, and last-modified time
    (truncated to whole seconds for SQLite-round-trip stability).  Any change
    to the file's content or modification time produces a different key,
    invalidating the cached thumbnails.
    """
    payload = f"{source_path.resolve()}:{file_size}:{int(mtime)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


class ThumbnailCache:
    """Persistent thumbnail cache backed by the repository layer.

    Thumbnails are stored as files under *cache_dir* with names of the form::

        {cache_key}_{size}.{format_extension}

    The cache is valid for a given (image, size) combination if and only if:
    1. A :class:`~engine.database.models.thumbnail.ThumbnailRecord` exists
       in the DB with a matching ``cache_key`` and ``size``.
    2. The corresponding file exists on disk and is non-empty.

    When the source file changes (different ``mtime`` or ``file_size``), the
    new cache_key will not match the stored one, and the thumbnails are
    regenerated automatically.
    """

    def __init__(
        self,
        cache_dir: Path,
        repository: ThumbnailRepository,
    ) -> None:
        self.cache_dir = cache_dir
        self.repository = repository

    # ------------------------------------------------------------------ #
    # Query                                                                #
    # ------------------------------------------------------------------ #

    def is_valid(self, image_id: int, cache_key: str, spec: ThumbnailSpec) -> bool:
        """Return ``True`` when a valid cached thumbnail exists for *spec*.

        Checks both the DB record and the on-disk file.
        """
        record = self.repository.get_by_image_and_size(image_id, spec.size)
        if record is None:
            return False
        if record.cache_key != cache_key:
            return False
        path = Path(record.file_path)
        return path.exists() and path.stat().st_size > 0

    def all_valid(self, image_id: int, cache_key: str, specs: list[ThumbnailSpec]) -> bool:
        """Return ``True`` when **all** *specs* are valid in the cache."""
        return all(self.is_valid(image_id, cache_key, spec) for spec in specs)

    def load_cached(
        self, image_id: int, cache_key: str, specs: list[ThumbnailSpec]
    ) -> list[GeneratedThumbnail]:
        """Return :class:`GeneratedThumbnail` objects for every cached spec."""
        results: list[GeneratedThumbnail] = []
        for spec in specs:
            record = self.repository.get_by_image_and_size(image_id, spec.size)
            if record is None or record.cache_key != cache_key:
                continue
            path = Path(record.file_path)
            if not path.exists():
                continue
            results.append(
                GeneratedThumbnail(
                    spec=spec,
                    file_path=path,
                    width=record.thumb_width,
                    height=record.thumb_height,
                    file_size_bytes=record.file_size_bytes,
                    cache_key=cache_key,
                )
            )
        return results

    # ------------------------------------------------------------------ #
    # Paths                                                                #
    # ------------------------------------------------------------------ #

    def thumbnail_path(self, cache_key: str, size: int, fmt: ThumbnailFormat) -> Path:
        """Return the destination path for a thumbnail, creating parent dirs."""
        # Shard into 256 subdirectories using the first two hex characters
        shard = cache_key[:2]
        target_dir = self.cache_dir / shard
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"{cache_key}_{size}.{fmt.value}"

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def persist(
        self,
        image_id: int,
        thumbnail: GeneratedThumbnail,
    ) -> None:
        """Upsert a thumbnail record in the repository."""
        existing = self.repository.get_by_image_and_size(image_id, thumbnail.spec.size)
        if existing is None:
            self.repository.create_thumbnail_record(
                image_id=image_id,
                size=thumbnail.spec.size,
                format=thumbnail.spec.format.value,
                file_path=str(thumbnail.file_path),
                file_size_bytes=thumbnail.file_size_bytes,
                cache_key=thumbnail.cache_key,
                thumb_width=thumbnail.width,
                thumb_height=thumbnail.height,
            )
        else:
            self.repository.update_thumbnail_record(
                existing,
                format=thumbnail.spec.format.value,
                file_path=str(thumbnail.file_path),
                file_size_bytes=thumbnail.file_size_bytes,
                cache_key=thumbnail.cache_key,
                thumb_width=thumbnail.width,
                thumb_height=thumbnail.height,
            )
