from __future__ import annotations

from pathlib import Path

from PIL import Image as PillowImage, UnidentifiedImageError

from engine.thumbnails.thumbnail_exceptions import CorruptedImageError, ThumbnailGenerationError
from engine.thumbnails.thumbnail_models import (
    DEFAULT_SIZES,
    GeneratedThumbnail,
    ThumbnailFormat,
    ThumbnailSpec,
)

# Pillow resampling filter – high quality, fast enough for thumbnails
_RESAMPLE = PillowImage.Resampling.LANCZOS

# Supported source formats (Pillow can open many more; these are the common ones)
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
        ".gif",
        ".tiff",
        ".tif",
        ".avif",
    }
)


class ThumbnailGenerator:
    """Pure-function thumbnail generator built on Pillow.

    Each call to :meth:`generate` opens the source image once, then derives
    all requested sizes from it, writing each result to disk before moving to
    the next.  Memory usage is therefore proportional to the source image
    dimensions, not to the number of requested sizes.
    """

    def generate(
        self,
        source_path: Path,
        specs: list[ThumbnailSpec],
        cache_dir: Path,
        cache_key: str,
        *,
        output_paths: dict[ThumbnailSpec, Path] | None = None,
    ) -> list[GeneratedThumbnail]:
        """Generate all *specs* for *source_path*.

        Parameters
        ----------
        source_path:
            Absolute path to the source image.
        specs:
            List of :class:`ThumbnailSpec` describing each variant to produce.
        cache_dir:
            Base directory for thumbnail storage (sharding is handled by the
            caller via *output_paths* or computed here).
        cache_key:
            Content-addressable key used in the output file name.
        output_paths:
            Optional explicit mapping of spec → destination path.  When
            omitted, paths are derived from *cache_dir* / *cache_key*.

        Raises
        ------
        CorruptedImageError
            If Pillow cannot open or decode the source file.
        ThumbnailGenerationError
            If thumbnail writing fails for any other reason.
        """
        try:
            img = PillowImage.open(source_path)
            img.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise CorruptedImageError(f"Cannot open image: {source_path}") from exc

        # Convert to RGB so we can safely save as JPEG/WebP without alpha issues
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")

        results: list[GeneratedThumbnail] = []
        for spec in specs:
            dest = (
                output_paths[spec]
                if output_paths and spec in output_paths
                else self._default_path(cache_dir, cache_key, spec)
            )
            thumb = self._generate_one(img, spec, dest, cache_key)
            results.append(thumb)

        return results

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _generate_one(
        img: PillowImage.Image,
        spec: ThumbnailSpec,
        dest: Path,
        cache_key: str,
    ) -> GeneratedThumbnail:
        src_w, src_h = img.size
        out_w, out_h = ThumbnailGenerator._compute_dimensions(src_w, src_h, spec.size)

        if out_w == src_w and out_h == src_h:
            # Source is already smaller than or equal to target; no upscaling
            resized = img
        else:
            resized = img.resize((out_w, out_h), _RESAMPLE)

        # Save – handle alpha channel for JPEG
        if spec.format in (ThumbnailFormat.JPEG,) and resized.mode in ("RGBA", "P"):
            resized = resized.convert("RGB")

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            save_kwargs: dict = {"quality": spec.quality}
            if spec.format == ThumbnailFormat.WEBP:
                save_kwargs["method"] = 4  # balanced speed/quality
            resized.save(str(dest), format=spec.format.value.upper(), **save_kwargs)
        except OSError as exc:
            raise ThumbnailGenerationError(f"Failed to write thumbnail: {dest}") from exc

        stat = dest.stat()
        return GeneratedThumbnail(
            spec=spec,
            file_path=dest,
            width=out_w,
            height=out_h,
            file_size_bytes=stat.st_size,
            cache_key=cache_key,
        )

    @staticmethod
    def _compute_dimensions(src_w: int, src_h: int, max_dim: int) -> tuple[int, int]:
        """Compute output (width, height) preserving aspect ratio, never upscaling."""
        if src_w == 0 or src_h == 0:
            return (max_dim, max_dim)
        # Never upscale
        if src_w <= max_dim and src_h <= max_dim:
            return (src_w, src_h)
        # Scale so the longest edge equals max_dim
        if src_w >= src_h:
            new_w = max_dim
            new_h = max(1, round(src_h * max_dim / src_w))
        else:
            new_h = max_dim
            new_w = max(1, round(src_w * max_dim / src_h))
        return (new_w, new_h)

    @staticmethod
    def _default_path(cache_dir: Path, cache_key: str, spec: ThumbnailSpec) -> Path:
        shard = cache_key[:2]
        return cache_dir / shard / f"{cache_key}_{spec.size}.{spec.format.value}"
