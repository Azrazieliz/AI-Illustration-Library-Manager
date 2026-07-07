"""Tests for the Hash Engine & Duplicate Detection Foundation (Commit 0009)."""
from __future__ import annotations

import hashlib
import io
import os
import time
from pathlib import Path

import pytest
from PIL import Image as PillowImage

from engine.config import settings
from engine.database.database import database_manager
from engine.hashing import (
    DuplicateCandidate,
    HashAlgorithm,
    HashCheckpoint,
    HashEngine,
    HashService,
)
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.repositories.hash_repository import HashRepository
from engine.repositories.image_repository import ImageRepository


# ------------------------------------------------------------------ #
# Shared fixture                                                       #
# ------------------------------------------------------------------ #


@pytest.fixture()
def hash_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace", tmp_path)
    monkeypatch.setattr(settings, "database_directory", Path("database"))
    monkeypatch.setattr(settings, "log_directory", tmp_path / "logs")
    monkeypatch.setattr(settings, "cache_directory", tmp_path / "cache")
    monkeypatch.setattr(settings, "thumbnail_directory", tmp_path / "cache" / "thumbnails")
    monkeypatch.setattr(settings, "embedding_directory", tmp_path / "cache" / "embeddings")
    monkeypatch.setattr(settings, "knowledge_directory", tmp_path / "knowledge")
    monkeypatch.setattr(settings, "models_directory", tmp_path / "models")
    monkeypatch.setattr(settings, "datasets_directory", tmp_path / "datasets")

    database_manager._engine = None
    database_manager._session_factory = None
    database_manager._initialized = False
    database_manager.__init__()


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def _make_png(tmp_path: Path, name: str, color: tuple[int, int, int] = (128, 64, 32)) -> Path:
    """Write a small solid-colour PNG to *tmp_path* and return its path."""
    img = PillowImage.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return path


def _register_image(path: Path) -> int:
    """Create an image record in the repository and return its id."""
    repo = ImageRepository()
    image = repo.create_image(
        original_path=str(path),
        filename=path.name,
        extension=path.suffix.lower(),
    )
    return image.id


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ #
# SHA-256 tests                                                        #
# ------------------------------------------------------------------ #


def test_sha256_matches_hashlib(hash_environment: None, tmp_path: Path) -> None:
    content = b"sha256 determinism test"
    p = tmp_path / "file.bin"
    p.write_bytes(content)
    _register_image(p)

    engine = HashEngine(algorithms=frozenset({HashAlgorithm.SHA256}))
    result = engine.hash_path(p)

    assert result is not None
    assert result.sha256 == hashlib.sha256(content).hexdigest()


def test_sha256_changes_when_content_changes(hash_environment: None, tmp_path: Path) -> None:
    p = tmp_path / "file.bin"
    p.write_bytes(b"version one")
    _register_image(p)

    engine = HashEngine(algorithms=frozenset({HashAlgorithm.SHA256}))
    r1 = engine.hash_path(p)
    assert r1 is not None

    p.write_bytes(b"version two")
    engine2 = HashEngine(algorithms=frozenset({HashAlgorithm.SHA256}))
    r2 = engine2.hash_path(p)
    assert r2 is not None

    assert r1.sha256 != r2.sha256


# ------------------------------------------------------------------ #
# Perceptual hash tests                                               #
# ------------------------------------------------------------------ #


def test_phash_same_image_deterministic(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "img.png", color=(200, 100, 50))
    _register_image(p)

    engine = HashEngine(algorithms=frozenset({HashAlgorithm.PHASH}))
    r1 = engine.hash_path(p)

    engine2 = HashEngine(algorithms=frozenset({HashAlgorithm.PHASH}))
    r2 = engine2.hash_path(p)

    assert r1 is not None and r2 is not None
    assert r1.phash == r2.phash
    assert r1.phash is not None
    assert len(r1.phash) == 16  # 64 bits = 16 hex chars


def test_phash_different_images_differ(hash_environment: None, tmp_path: Path) -> None:
    # Use structurally distinct images: a checkerboard (high spatial frequency) vs
    # a linear gradient (low spatial frequency). Their DCT profiles are very different.
    def _make_checkerboard(path: Path, cell: int = 8) -> None:
        img = PillowImage.new("L", (64, 64))
        pix = img.load()
        for x in range(64):
            for y in range(64):
                pix[x, y] = 255 if ((x // cell + y // cell) % 2 == 0) else 0
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        path.write_bytes(buf.getvalue())

    def _make_horizontal_gradient(path: Path) -> None:
        img = PillowImage.new("L", (64, 64))
        pix = img.load()
        for x in range(64):
            for y in range(64):
                pix[x, y] = int(x * 255 / 63)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        path.write_bytes(buf.getvalue())

    p1 = tmp_path / "checker.png"
    p2 = tmp_path / "gradient.png"
    _make_checkerboard(p1)
    _make_horizontal_gradient(p2)
    _register_image(p1)
    _register_image(p2)

    engine = HashEngine(algorithms=frozenset({HashAlgorithm.PHASH}))
    r1 = engine.hash_path(p1)
    r2 = engine.hash_path(p2)

    assert r1 is not None and r2 is not None
    assert r1.phash != r2.phash


def test_ahash_same_image_deterministic(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "img.png")
    _register_image(p)

    engine = HashEngine(algorithms=frozenset({HashAlgorithm.AHASH}))
    r1 = engine.hash_path(p)
    engine2 = HashEngine(algorithms=frozenset({HashAlgorithm.AHASH}))
    r2 = engine2.hash_path(p)

    assert r1 is not None and r2 is not None
    assert r1.ahash == r2.ahash
    assert r1.ahash is not None
    assert len(r1.ahash) == 16


def test_ahash_different_images_differ(hash_environment: None, tmp_path: Path) -> None:
    # Uniform images are perceptually identical under aHash (all pixels equal the mean).
    # Use a left-to-right gradient vs a right-to-left gradient: each will set opposite
    # halves of the 8×8 grid above/below the mean, producing complementary bit patterns.
    def _make_lr_gradient(path: Path, left_to_right: bool) -> None:
        img = PillowImage.new("L", (64, 64))
        pix = img.load()
        for x in range(64):
            v = int(x * 255 / 63) if left_to_right else int((63 - x) * 255 / 63)
            for y in range(64):
                pix[x, y] = v
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        path.write_bytes(buf.getvalue())

    p1 = tmp_path / "lr.png"
    p2 = tmp_path / "rl.png"
    _make_lr_gradient(p1, left_to_right=True)
    _make_lr_gradient(p2, left_to_right=False)
    _register_image(p1)
    _register_image(p2)

    engine = HashEngine(algorithms=frozenset({HashAlgorithm.AHASH}))
    r1 = engine.hash_path(p1)
    r2 = engine.hash_path(p2)

    assert r1 is not None and r2 is not None
    assert r1.ahash != r2.ahash


def test_dhash_same_image_deterministic(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "img.png")
    _register_image(p)

    engine = HashEngine(algorithms=frozenset({HashAlgorithm.DHASH}))
    r1 = engine.hash_path(p)
    engine2 = HashEngine(algorithms=frozenset({HashAlgorithm.DHASH}))
    r2 = engine2.hash_path(p)

    assert r1 is not None and r2 is not None
    assert r1.dhash == r2.dhash
    assert r1.dhash is not None
    assert len(r1.dhash) == 16


def test_dhash_different_images_differ(hash_environment: None, tmp_path: Path) -> None:
    # Create images with distinct horizontal gradient directions
    def _gradient(tmp_path: Path, name: str, left_dark: bool) -> Path:
        img = PillowImage.new("RGB", (64, 64))
        pixels = img.load()
        for x in range(64):
            val = x * 4 if not left_dark else (255 - x * 4)
            for y in range(64):
                pixels[x, y] = (val, val, val)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        p = tmp_path / name
        p.write_bytes(buf.getvalue())
        return p

    p1 = _gradient(tmp_path, "grad_light_to_dark.png", left_dark=False)
    p2 = _gradient(tmp_path, "grad_dark_to_light.png", left_dark=True)
    _register_image(p1)
    _register_image(p2)

    engine = HashEngine(algorithms=frozenset({HashAlgorithm.DHASH}))
    r1 = engine.hash_path(p1)
    r2 = engine.hash_path(p2)

    assert r1 is not None and r2 is not None
    assert r1.dhash != r2.dhash


# ------------------------------------------------------------------ #
# Non-image files                                                      #
# ------------------------------------------------------------------ #


def test_non_image_file_gets_sha256_only(hash_environment: None, tmp_path: Path) -> None:
    p = tmp_path / "data.bin"
    p.write_bytes(os.urandom(256))
    _register_image(p)

    engine = HashEngine()
    result = engine.hash_path(p)

    assert result is not None
    assert result.sha256 != ""
    assert result.phash is None
    assert result.ahash is None
    assert result.dhash is None


# ------------------------------------------------------------------ #
# Crash recovery / restart                                             #
# ------------------------------------------------------------------ #


def test_restart_recovery_skips_already_hashed_file(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "img.png")
    _register_image(p)

    engine = HashEngine()
    r1 = engine.hash_path(p)
    assert r1 is not None
    assert engine.statistics.hashed == 1

    # Second engine instance – same file, same content → cache hit
    engine2 = HashEngine()
    r2 = engine2.hash_path(p)
    assert r2 is not None
    assert r2.sha256 == r1.sha256
    assert r2.phash == r1.phash
    assert engine2.statistics.skipped == 1
    assert engine2.statistics.hashed == 0


def test_checkpoint_prevents_reprocessing(hash_environment: None, tmp_path: Path) -> None:
    p1 = _make_png(tmp_path, "a.png", color=(10, 20, 30))
    p2 = _make_png(tmp_path, "b.png", color=(40, 50, 60))
    _register_image(p1)
    _register_image(p2)

    # Simulate crash after p1 was processed
    checkpoint = HashCheckpoint(processed_paths={str(p1)})

    engine = HashEngine()
    results = engine.hash_paths([p1, p2], checkpoint=checkpoint)

    # Only p2 should be hashed
    assert len(results) == 1
    assert results[0].source_path == str(p2)
    assert engine.statistics.hashed == 1
    assert engine.statistics.skipped == 1


def test_modified_file_is_rehashed(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "img.png", color=(1, 2, 3))
    _register_image(p)

    engine1 = HashEngine()
    r1 = engine1.hash_path(p)
    assert r1 is not None

    # Replace file content and advance mtime
    new_img = PillowImage.new("RGB", (64, 64), (200, 200, 200))
    buf = io.BytesIO()
    new_img.save(buf, format="PNG")
    new_content = buf.getvalue()
    p.write_bytes(new_content)
    new_mtime = time.time() + 2
    os.utime(p, (new_mtime, new_mtime))

    engine2 = HashEngine()
    r2 = engine2.hash_path(p)
    assert r2 is not None
    assert r2.sha256 != r1.sha256
    assert engine2.statistics.hashed == 1


# ------------------------------------------------------------------ #
# Repository persistence                                               #
# ------------------------------------------------------------------ #


def test_hash_persisted_to_repository(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "persist.png")
    image_id = _register_image(p)

    engine = HashEngine()
    result = engine.hash_path(p)
    assert result is not None

    repo = HashRepository()
    record = repo.get_by_image_id(image_id)
    assert record is not None
    assert record.sha256 == result.sha256
    assert record.phash == result.phash
    assert record.ahash == result.ahash
    assert record.dhash == result.dhash


def test_hash_updated_when_file_changes(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "update.png", color=(10, 10, 10))
    image_id = _register_image(p)

    engine1 = HashEngine()
    engine1.hash_path(p)

    new_img = PillowImage.new("RGB", (64, 64), (240, 240, 240))
    buf = io.BytesIO()
    new_img.save(buf, format="PNG")
    p.write_bytes(buf.getvalue())
    new_mtime = time.time() + 2
    os.utime(p, (new_mtime, new_mtime))

    engine2 = HashEngine()
    result2 = engine2.hash_path(p)
    assert result2 is not None

    repo = HashRepository()
    record = repo.get_by_image_id(image_id)
    assert record is not None
    assert record.sha256 == result2.sha256


# ------------------------------------------------------------------ #
# Queue integration                                                    #
# ------------------------------------------------------------------ #


def test_hash_service_publishes_duplicate_job(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "queued.png")
    _register_image(p)

    queue_manager = QueueManager()
    service = HashService(queue_manager=queue_manager)

    job = PipelineJob(source_path=str(p), queue_type=QueueType.HASH)
    candidate = service.process_hash_job(job)

    assert candidate is not None
    assert isinstance(candidate, DuplicateCandidate)
    assert candidate.sha256 != ""

    dup_job = queue_manager.dequeue(QueueType.DUPLICATE)
    assert dup_job is not None
    assert dup_job.source_path == str(p)
    assert dup_job.metadata.get("sha256") == candidate.sha256


def test_hash_service_skips_job_without_source_path(hash_environment: None, tmp_path: Path) -> None:
    queue_manager = QueueManager()
    service = HashService(queue_manager=queue_manager)

    job = PipelineJob(source_path=None, queue_type=QueueType.HASH)
    result = service.process_hash_job(job)

    assert result is None
    assert queue_manager.dequeue(QueueType.DUPLICATE) is None


def test_hash_service_skips_unregistered_file(hash_environment: None, tmp_path: Path) -> None:
    """A file that has no image record in the DB must not crash the service."""
    p = _make_png(tmp_path, "orphan.png")
    # intentionally NOT calling _register_image

    queue_manager = QueueManager()
    service = HashService(queue_manager=queue_manager)

    job = PipelineJob(source_path=str(p), queue_type=QueueType.HASH)
    candidate = service.process_hash_job(job)

    # SHA-256 will be computed, perceptual hashes will be computed, but no
    # persist call is made (no image record), so no duplicate job is published.
    assert candidate is None
    assert queue_manager.dequeue(QueueType.DUPLICATE) is None


# ------------------------------------------------------------------ #
# DuplicateCandidate structure                                         #
# ------------------------------------------------------------------ #


def test_duplicate_candidate_has_all_hashes(hash_environment: None, tmp_path: Path) -> None:
    p = _make_png(tmp_path, "candidate.png")
    image_id = _register_image(p)

    engine = HashEngine()
    result = engine.hash_path(p)
    assert result is not None

    candidate = engine.make_duplicate_candidate(result, image_id)

    assert candidate.source_path == str(p)
    assert candidate.image_id == image_id
    assert candidate.sha256 == result.sha256
    assert candidate.phash == result.phash
    assert candidate.ahash == result.ahash
    assert candidate.dhash == result.dhash
    assert candidate.prepared_at is not None
