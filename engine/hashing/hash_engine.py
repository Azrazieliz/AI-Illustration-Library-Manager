from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image as PillowImage
from PIL import UnidentifiedImageError

from engine.hashing.hash_events import FileHashed, HashCompleted, HashFailed, HashStarted
from engine.hashing.hash_exceptions import (
    HashComputationError,
    HashPersistenceError,
    UnsupportedImageFormatError,
)
from engine.hashing.hash_models import (
    DuplicateCandidate,
    HashAlgorithm,
    HashCheckpoint,
    HashResult,
)
from engine.hashing.hash_statistics import HashStatistics
from engine.repositories.hash_repository import HashRepository
from engine.repositories.image_repository import ImageRepository

_DEFAULT_ALGORITHMS: frozenset[HashAlgorithm] = frozenset(
    {
        HashAlgorithm.SHA256,
        HashAlgorithm.PHASH,
        HashAlgorithm.AHASH,
        HashAlgorithm.DHASH,
    }
)

_PERCEPTUAL_ALGORITHMS: frozenset[HashAlgorithm] = frozenset(
    {
        HashAlgorithm.PHASH,
        HashAlgorithm.AHASH,
        HashAlgorithm.DHASH,
    }
)


class HashEngine:
    """Computes SHA-256, pHash, aHash, and dHash for image files.

    The engine is designed to be called from a pipeline worker that
    consumes jobs from the HASH queue.  It stores results through
    the repository layer and never touches SQLAlchemy directly.

    Crash recovery
    --------------
    If a run is interrupted the caller can pass a :class:`HashCheckpoint`
    populated with the set of paths that were already processed.  On the
    next invocation, those paths are skipped automatically.

    Additionally, before computing perceptual hashes, the engine checks
    whether the file's SHA-256 already matches a stored hash record.  If it
    does, the file is returned from the cache without re-hashing its
    perceptual content.
    """

    def __init__(
        self,
        *,
        image_repository: ImageRepository | None = None,
        hash_repository: HashRepository | None = None,
        callback: Callable[[object], None] | None = None,
        algorithms: frozenset[HashAlgorithm] | None = None,
    ) -> None:
        self.image_repository = image_repository or ImageRepository()
        self.hash_repository = hash_repository or HashRepository()
        self.callback = callback
        self.algorithms: frozenset[HashAlgorithm] = algorithms or _DEFAULT_ALGORITHMS
        self.statistics = HashStatistics()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def hash_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: HashCheckpoint | None = None,
    ) -> list[HashResult]:
        """Hash all *paths* and return a :class:`HashResult` for each.

        Files that are skipped (checkpoint or cache hit) are not included in
        the returned list but are counted in ``statistics.skipped``.
        """
        self.statistics = HashStatistics()
        self.statistics.start()
        results: list[HashResult] = []

        for raw_path in paths:
            resolved = Path(raw_path).resolve()

            if checkpoint is not None and str(resolved) in checkpoint.processed_paths:
                self.statistics.skipped += 1
                self.statistics.processed += 1
                continue

            cached = self._check_cache(resolved)
            if cached is not None:
                results.append(cached)
                self.statistics.skipped += 1
                self.statistics.processed += 1
                if checkpoint is not None:
                    checkpoint.processed_paths.add(str(resolved))
                continue

            try:
                result = self._compute(resolved)
                results.append(result)
                if checkpoint is not None:
                    checkpoint.processed_paths.add(str(resolved))
                self.statistics.hashed += 1
                self.statistics.processed += 1
            except (HashComputationError, UnsupportedImageFormatError, OSError) as exc:
                self.statistics.failed += 1
                self.statistics.processed += 1
                self._emit(HashFailed(path=resolved, error=str(exc)))

        self.statistics.complete()
        self._emit(HashCompleted(total=self.statistics.hashed, failed=self.statistics.failed))
        return results

    def hash_path(
        self,
        path: Path | str,
        *,
        checkpoint: HashCheckpoint | None = None,
    ) -> HashResult | None:
        """Convenience wrapper to hash a single *path*."""
        results = self.hash_paths([path], checkpoint=checkpoint)
        return results[0] if results else None

    def make_duplicate_candidate(self, result: HashResult, image_id: int) -> DuplicateCandidate:
        """Build a :class:`DuplicateCandidate` from a :class:`HashResult`."""
        return DuplicateCandidate(
            source_path=result.source_path,
            image_id=image_id,
            sha256=result.sha256,
            phash=result.phash,
            ahash=result.ahash,
            dhash=result.dhash,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _check_cache(self, path: Path) -> HashResult | None:
        """Return a cached :class:`HashResult` if the file is unchanged.

        Computes SHA-256 once and compares it to the stored value.  If they
        match, all hashes are served from the repository without re-reading
        the image.  Returns ``None`` when no valid cache entry exists.
        """
        if HashAlgorithm.SHA256 not in self.algorithms:
            return None
        image = self.image_repository.get_by_path(str(path))
        if image is None or image.id is None:
            return None
        existing = self.hash_repository.get_by_image_id(image.id)
        if existing is None:
            return None
        # Only skip if the on-disk content matches what was previously stored
        current_sha256 = self._compute_sha256(path)
        if existing.sha256 != current_sha256:
            return None
        return HashResult(
            source_path=str(path),
            sha256=existing.sha256,
            phash=existing.phash,
            ahash=existing.ahash,
            dhash=existing.dhash,
        )

    def _compute(self, path: Path) -> HashResult:
        """Compute all configured hashes for *path* and persist them."""
        if not path.exists():
            raise HashComputationError(f"File not found: {path}")

        self._emit(HashStarted(path=path))

        sha256 = self._compute_sha256(path) if HashAlgorithm.SHA256 in self.algorithms else ""
        phash: str | None = None
        ahash: str | None = None
        dhash: str | None = None

        if _PERCEPTUAL_ALGORITHMS & self.algorithms:
            try:
                img = self._open_image(path)
                if HashAlgorithm.PHASH in self.algorithms:
                    phash = self._compute_phash(img)
                if HashAlgorithm.AHASH in self.algorithms:
                    ahash = self._compute_ahash(img)
                if HashAlgorithm.DHASH in self.algorithms:
                    dhash = self._compute_dhash(img)
            except UnsupportedImageFormatError:
                # Non-image files receive None for all perceptual hashes
                pass

        result = HashResult(
            source_path=str(path),
            sha256=sha256,
            phash=phash,
            ahash=ahash,
            dhash=dhash,
        )
        self._persist(result)
        self._emit(FileHashed(path=path, sha256=sha256))
        return result

    def _persist(self, result: HashResult) -> None:
        """Store *result* through the repository layer."""
        image = self.image_repository.get_by_path(result.source_path)
        if image is None:
            return
        try:
            existing = self.hash_repository.get_by_image_id(image.id)
            if existing is None:
                self.hash_repository.create_hash_record(
                    image_id=image.id,
                    sha256=result.sha256,
                    phash=result.phash,
                    ahash=result.ahash,
                    dhash=result.dhash,
                )
            else:
                self.hash_repository.update_hash_record(
                    existing,
                    sha256=result.sha256,
                    phash=result.phash,
                    ahash=result.ahash,
                    dhash=result.dhash,
                )
            # Mirror sha256/phash onto the image record for quick lookup
            image.sha256 = result.sha256
            image.phash = result.phash
            self.image_repository.commit()
        except Exception as exc:
            raise HashPersistenceError(f"Failed to persist hash for {result.source_path}") from exc

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)

    # ------------------------------------------------------------------ #
    # Hash computation – static methods                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        """Return the lowercase hex SHA-256 of *path*'s raw bytes."""
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _open_image(path: Path) -> PillowImage.Image:
        """Open *path* as a Pillow image; raise :exc:`UnsupportedImageFormatError` on failure."""
        try:
            img = PillowImage.open(path)
            img.load()
            return img
        except (UnidentifiedImageError, OSError) as exc:
            raise UnsupportedImageFormatError(f"Cannot open image: {path}") from exc

    @staticmethod
    def _compute_phash(img: PillowImage.Image, hash_size: int = 8, highfreq_factor: int = 4) -> str:
        """Perceptual hash (pHash) via 2-D DCT.

        Algorithm
        ---------
        1. Convert to greyscale and resize to ``hash_size * highfreq_factor``
           (default 32 × 32).
        2. Compute the 2-D DCT-II.
        3. Retain the top-left ``hash_size × hash_size`` (default 8 × 8) block
           of low-frequency coefficients.
        4. Compute the mean of those coefficients excluding the DC component
           at position [0, 0].
        5. Set each bit to 1 where the coefficient exceeds the mean.
        6. Return the 64-bit value as a zero-padded lowercase hex string.
        """
        img_size = hash_size * highfreq_factor
        gray = img.convert("L").resize((img_size, img_size), PillowImage.Resampling.LANCZOS)
        pixels = np.asarray(gray, dtype=np.float64)
        dct = HashEngine._dct2d(pixels)
        low = dct[:hash_size, :hash_size]
        flat = low.flatten()
        mean = (flat.sum() - flat[0]) / (len(flat) - 1)
        bits = flat > mean
        val = 0
        for bit in bits:
            val = (val << 1) | int(bit)
        hex_len = hash_size * hash_size // 4
        return format(val, f"0{hex_len}x")

    @staticmethod
    def _compute_ahash(img: PillowImage.Image, hash_size: int = 8) -> str:
        """Average hash (aHash).

        Algorithm
        ---------
        1. Convert to greyscale and resize to ``hash_size × hash_size``
           (default 8 × 8).
        2. Compute the mean pixel value.
        3. Set each bit to 1 where the pixel is ≥ the mean.
        4. Return the 64-bit value as a zero-padded lowercase hex string.
        """
        gray = img.convert("L").resize((hash_size, hash_size), PillowImage.Resampling.LANCZOS)
        pixels = np.asarray(gray, dtype=np.float64)
        mean = pixels.mean()
        bits = pixels.flatten() >= mean
        val = 0
        for bit in bits:
            val = (val << 1) | int(bit)
        hex_len = hash_size * hash_size // 4
        return format(val, f"0{hex_len}x")

    @staticmethod
    def _compute_dhash(img: PillowImage.Image, hash_size: int = 8) -> str:
        """Difference hash (dHash).

        Algorithm
        ---------
        1. Convert to greyscale and resize to ``(hash_size + 1) × hash_size``
           (default 9 × 8).
        2. For each row, compare each pixel to its right neighbour.
        3. Set each bit to 1 where the left pixel exceeds the right pixel.
        4. Return the 64-bit value as a zero-padded lowercase hex string.
        """
        gray = img.convert("L").resize(
            (hash_size + 1, hash_size), PillowImage.Resampling.LANCZOS
        )
        pixels = np.asarray(gray, dtype=np.int32)
        diff = pixels[:, :-1] > pixels[:, 1:]  # shape: (hash_size, hash_size)
        bits = diff.flatten()
        val = 0
        for bit in bits:
            val = (val << 1) | int(bit)
        hex_len = hash_size * hash_size // 4
        return format(val, f"0{hex_len}x")

    @staticmethod
    def _dct1d(x: np.ndarray) -> np.ndarray:
        """1-D DCT-II via FFT (unnormalized, no scipy required).

        Uses the standard zero-phase FFT trick: append the reversed input to
        create a symmetric sequence of length 2N, take the N-point rfft, then
        multiply by the phase factor ``exp(-j·π·k / 2N)``.
        """
        n = x.shape[0]
        y = np.empty(2 * n, dtype=np.float64)
        y[:n] = x
        y[n:] = x[::-1]
        Y = np.fft.rfft(y)[:n]
        k = np.arange(n, dtype=np.float64)
        return (Y * np.exp(-1j * np.pi * k / (2.0 * n))).real

    @staticmethod
    def _dct2d(pixels: np.ndarray) -> np.ndarray:
        """2-D DCT-II via separable 1-D DCT along rows then columns."""
        rows_dct = np.apply_along_axis(HashEngine._dct1d, axis=1, arr=pixels)
        return np.apply_along_axis(HashEngine._dct1d, axis=0, arr=rows_dct)
