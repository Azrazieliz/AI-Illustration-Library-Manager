"""Tests for the Duplicate Detection Engine (Commit 0010)."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image as PillowImage

from engine.config import settings
from engine.database.database import database_manager
from engine.duplicates import (
    ConfidenceLevel,
    DuplicateCheckpoint,
    DuplicateEngine,
    DuplicateMatcher,
    DuplicatePair,
    DuplicateService,
    MatchType,
    SimilarityThresholds,
    SimilarityWeights,
    hamming_distance,
    normalized_hamming,
)
from engine.hashing.hash_models import DuplicateCandidate
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.hash_repository import HashRepository
from engine.repositories.image_repository import ImageRepository


# ------------------------------------------------------------------ #
# Shared fixture                                                       #
# ------------------------------------------------------------------ #


@pytest.fixture()
def dup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _png_bytes(color: tuple[int, int, int] = (128, 64, 32), size: int = 64) -> bytes:
    img = PillowImage.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _register_image(path: Path) -> int:
    repo = ImageRepository()
    img = repo.create_image(
        original_path=str(path), filename=path.name, extension=path.suffix
    )
    return img.id


def _make_candidate(
    tmp_path: Path,
    name: str,
    color: tuple[int, int, int],
    image_id: int,
    phash: str = "0" * 16,
    ahash: str = "0" * 16,
    dhash: str = "0" * 16,
) -> DuplicateCandidate:
    data = _png_bytes(color)
    path = tmp_path / name
    path.write_bytes(data)
    return DuplicateCandidate(
        source_path=str(path),
        image_id=image_id,
        sha256=_sha256(data),
        phash=phash,
        ahash=ahash,
        dhash=dhash,
    )


# ------------------------------------------------------------------ #
# Hamming distance                                                     #
# ------------------------------------------------------------------ #


def test_hamming_distance_identical() -> None:
    assert hamming_distance("0" * 16, "0" * 16) == 0
    assert hamming_distance("f" * 16, "f" * 16) == 0


def test_hamming_distance_completely_different() -> None:
    # 0x0000...0000 XOR 0xffff...ffff = all 1s → 64 bits differ
    assert hamming_distance("0" * 16, "f" * 16) == 64


def test_hamming_distance_one_bit() -> None:
    # 0x0000000000000000 vs 0x0000000000000001 → 1 bit differs
    assert hamming_distance("0000000000000000", "0000000000000001") == 1


def test_hamming_distance_symmetric() -> None:
    a, b = "deadbeef01234567", "cafebabe89abcdef"
    assert hamming_distance(a, b) == hamming_distance(b, a)


def test_normalized_hamming_range() -> None:
    score = normalized_hamming("0" * 16, "f" * 16)
    assert score == 1.0
    score = normalized_hamming("0" * 16, "0" * 16)
    assert score == 0.0


def test_hamming_distance_length_mismatch_raises() -> None:
    from engine.duplicates import InvalidHashError

    with pytest.raises(InvalidHashError):
        hamming_distance("abc", "abcd")


# ------------------------------------------------------------------ #
# Weighted similarity scoring                                          #
# ------------------------------------------------------------------ #


def test_similarity_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError):
        SimilarityWeights(phash=0.5, ahash=0.5, dhash=0.5)


def test_similarity_weights_custom() -> None:
    weights = SimilarityWeights(phash=0.6, ahash=0.2, dhash=0.2)
    assert abs(weights.phash + weights.ahash + weights.dhash - 1.0) < 1e-9


def test_thresholds_ordering_enforced() -> None:
    with pytest.raises(ValueError):
        SimilarityThresholds(high=0.5, medium=0.3, low=0.8)


def test_matcher_produces_high_confidence_for_near_identical_hashes() -> None:
    near_identical = "0000000000000001"  # 1 bit away from "0" * 16
    matcher = DuplicateMatcher(thresholds=SimilarityThresholds(high=0.10))
    ca = DuplicateCandidate(
        source_path="/a.png", image_id=1, sha256="aaa",
        phash="0" * 16, ahash="0" * 16, dhash="0" * 16,
    )
    cb = DuplicateCandidate(
        source_path="/b.png", image_id=2, sha256="bbb",
        phash=near_identical, ahash=near_identical, dhash=near_identical,
    )
    matcher.add_candidate(ca)
    pairs = matcher.find_matches(cb)
    assert len(pairs) == 1
    assert pairs[0].confidence == ConfidenceLevel.HIGH


def test_matcher_rejects_dissimilar_images() -> None:
    matcher = DuplicateMatcher(thresholds=SimilarityThresholds(high=0.05, medium=0.10, low=0.20))
    ca = DuplicateCandidate(
        source_path="/a.png", image_id=1, sha256="aaa",
        phash="0" * 16, ahash="0" * 16, dhash="0" * 16,
    )
    cb = DuplicateCandidate(
        source_path="/b.png", image_id=2, sha256="bbb",
        phash="f" * 16, ahash="f" * 16, dhash="f" * 16,
    )
    matcher.add_candidate(ca)
    pairs = matcher.find_matches(cb)
    assert len(pairs) == 0


# ------------------------------------------------------------------ #
# Exact duplicate detection                                            #
# ------------------------------------------------------------------ #


def test_exact_duplicate_detected(dup_env: None, tmp_path: Path) -> None:
    data = _png_bytes((100, 150, 200))
    sha = _sha256(data)

    p1 = tmp_path / "img1.png"
    p2 = tmp_path / "img2.png"
    p1.write_bytes(data)
    p2.write_bytes(data)  # identical content

    id1 = _register_image(p1)
    id2 = _register_image(p2)

    ca = DuplicateCandidate(source_path=str(p1), image_id=id1, sha256=sha)
    cb = DuplicateCandidate(source_path=str(p2), image_id=id2, sha256=sha)

    engine = DuplicateEngine()
    engine._matcher.add_candidate(ca)
    pairs = engine.process_candidate(cb)

    assert len(pairs) == 1
    assert pairs[0].match_type == MatchType.EXACT
    assert pairs[0].sha256_match is True
    assert pairs[0].overall_score == 1.0
    assert pairs[0].confidence == ConfidenceLevel.HIGH


def test_exact_duplicate_canonical_ordering(dup_env: None, tmp_path: Path) -> None:
    """The pair's image_a_id must always be the lower integer."""
    data = _png_bytes()
    sha = _sha256(data)
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    p1.write_bytes(data)
    p2.write_bytes(data)
    id1 = _register_image(p1)
    id2 = _register_image(p2)

    ca = DuplicateCandidate(source_path=str(p1), image_id=id1, sha256=sha)
    cb = DuplicateCandidate(source_path=str(p2), image_id=id2, sha256=sha)

    engine = DuplicateEngine()
    engine._matcher.add_candidate(cb)  # note: b registered first
    pairs = engine.process_candidate(ca)

    assert len(pairs) == 1
    assert pairs[0].image_a_id < pairs[0].image_b_id


# ------------------------------------------------------------------ #
# Perceptual duplicate detection                                       #
# ------------------------------------------------------------------ #


def test_perceptual_duplicate_detected(dup_env: None, tmp_path: Path) -> None:
    similar_hash = "0000000000000001"  # 1-bit Hamming distance from all-zeros

    p1 = tmp_path / "img1.png"
    p2 = tmp_path / "img2.png"
    p1.write_bytes(_png_bytes((1, 2, 3)))
    p2.write_bytes(_png_bytes((4, 5, 6)))
    id1 = _register_image(p1)
    id2 = _register_image(p2)

    ca = DuplicateCandidate(
        source_path=str(p1), image_id=id1, sha256="aaa",
        phash="0" * 16, ahash="0" * 16, dhash="0" * 16,
    )
    cb = DuplicateCandidate(
        source_path=str(p2), image_id=id2, sha256="bbb",
        phash=similar_hash, ahash=similar_hash, dhash=similar_hash,
    )

    engine = DuplicateEngine()
    engine._matcher.add_candidate(ca)
    pairs = engine.process_candidate(cb)

    assert len(pairs) == 1
    assert pairs[0].match_type == MatchType.PERCEPTUAL
    assert pairs[0].distances.phash == 1
    assert pairs[0].distances.ahash == 1
    assert pairs[0].distances.dhash == 1


def test_different_images_not_flagged(dup_env: None, tmp_path: Path) -> None:
    p1 = tmp_path / "img1.png"
    p2 = tmp_path / "img2.png"
    p1.write_bytes(_png_bytes((0, 0, 0)))
    p2.write_bytes(_png_bytes((255, 255, 255)))
    id1 = _register_image(p1)
    id2 = _register_image(p2)

    ca = DuplicateCandidate(
        source_path=str(p1), image_id=id1, sha256="aaa",
        phash="0" * 16, ahash="0" * 16, dhash="0" * 16,
    )
    cb = DuplicateCandidate(
        source_path=str(p2), image_id=id2, sha256="bbb",
        phash="f" * 16, ahash="f" * 16, dhash="f" * 16,
    )

    engine = DuplicateEngine()
    engine._matcher.add_candidate(ca)
    pairs = engine.process_candidate(cb)

    assert len(pairs) == 0


# ------------------------------------------------------------------ #
# Repository persistence                                               #
# ------------------------------------------------------------------ #


def test_duplicate_pair_persisted(dup_env: None, tmp_path: Path) -> None:
    data = _png_bytes((10, 20, 30))
    sha = _sha256(data)
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    p1.write_bytes(data)
    p2.write_bytes(data)
    id1 = _register_image(p1)
    id2 = _register_image(p2)

    ca = DuplicateCandidate(source_path=str(p1), image_id=id1, sha256=sha)
    cb = DuplicateCandidate(source_path=str(p2), image_id=id2, sha256=sha)

    engine = DuplicateEngine()
    engine._matcher.add_candidate(ca)
    engine.process_candidate(cb)

    repo = DuplicateRepository()
    records = repo.list_all_duplicates()
    assert len(records) == 1
    assert records[0].match_type == "exact"
    assert records[0].overall_score == 1.0


def test_duplicate_not_double_persisted(dup_env: None, tmp_path: Path) -> None:
    """Processing the same pair twice must not create two DB records."""
    data = _png_bytes()
    sha = _sha256(data)
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    p1.write_bytes(data)
    p2.write_bytes(data)
    id1 = _register_image(p1)
    id2 = _register_image(p2)

    ca = DuplicateCandidate(source_path=str(p1), image_id=id1, sha256=sha)
    cb = DuplicateCandidate(source_path=str(p2), image_id=id2, sha256=sha)

    engine = DuplicateEngine()
    engine._matcher.add_candidate(ca)
    engine.process_candidate(cb)
    # process again with a fresh engine (simulates restart)
    engine2 = DuplicateEngine()
    engine2._matcher.add_candidate(ca)
    engine2.process_candidate(cb)

    repo = DuplicateRepository()
    assert len(repo.list_all_duplicates()) == 1


# ------------------------------------------------------------------ #
# Crash recovery                                                       #
# ------------------------------------------------------------------ #


def test_checkpoint_prevents_recomparison(dup_env: None, tmp_path: Path) -> None:
    data = _png_bytes()
    sha = _sha256(data)
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    p1.write_bytes(data)
    p2.write_bytes(data)
    id1 = _register_image(p1)
    id2 = _register_image(p2)

    ca = DuplicateCandidate(source_path=str(p1), image_id=id1, sha256=sha)
    cb = DuplicateCandidate(source_path=str(p2), image_id=id2, sha256=sha)

    # Simulate a checkpoint that already contains this pair
    checkpoint = DuplicateCheckpoint(
        compared_pairs={frozenset({id1, id2})}
    )

    engine = DuplicateEngine()
    engine._matcher.add_candidate(ca)
    pairs = engine.process_candidate(cb, checkpoint=checkpoint)

    # The pair was in the checkpoint → no new comparison performed
    assert len(pairs) == 0


# ------------------------------------------------------------------ #
# Queue integration                                                    #
# ------------------------------------------------------------------ #


def test_service_publishes_review_job(dup_env: None, tmp_path: Path) -> None:
    data = _png_bytes((77, 88, 99))
    sha = _sha256(data)
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    p1.write_bytes(data)
    p2.write_bytes(data)
    id1 = _register_image(p1)
    id2 = _register_image(p2)

    # Pre-register image_a in the hash repo and in the engine via existing hash
    hash_repo = HashRepository()
    hash_repo.create_hash_record(image_id=id1, sha256=sha)

    qm = QueueManager()
    engine = DuplicateEngine()
    service = DuplicateService(queue_manager=qm, engine=engine)

    job = PipelineJob(
        source_path=str(p2),
        queue_type=QueueType.DUPLICATE,
        metadata={"sha256": sha},
    )
    pairs = service.process_duplicate_job(job)

    assert len(pairs) == 1
    review_job = qm.dequeue(QueueType.REVIEW)
    assert review_job is not None
    assert review_job.metadata["match_type"] == "exact"
    assert review_job.metadata["confidence"] == "high"


def test_service_skips_job_without_sha256(dup_env: None, tmp_path: Path) -> None:
    p = tmp_path / "a.png"
    p.write_bytes(_png_bytes())
    _register_image(p)

    qm = QueueManager()
    service = DuplicateService(queue_manager=qm)

    job = PipelineJob(
        source_path=str(p),
        queue_type=QueueType.DUPLICATE,
        metadata={},  # no sha256
    )
    pairs = service.process_duplicate_job(job)
    assert pairs == []
    assert qm.dequeue(QueueType.REVIEW) is None


def test_service_skips_job_with_unknown_path(dup_env: None, tmp_path: Path) -> None:
    qm = QueueManager()
    service = DuplicateService(queue_manager=qm)

    job = PipelineJob(
        source_path=str(tmp_path / "nonexistent.png"),
        queue_type=QueueType.DUPLICATE,
        metadata={"sha256": "abc123"},
    )
    pairs = service.process_duplicate_job(job)
    assert pairs == []


# ------------------------------------------------------------------ #
# Statistics                                                           #
# ------------------------------------------------------------------ #


def test_statistics_updated_correctly(dup_env: None, tmp_path: Path) -> None:
    data = _png_bytes()
    sha = _sha256(data)
    p1, p2, p3 = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png"
    for p in (p1, p2, p3):
        p.write_bytes(data)
    id1, id2, id3 = _register_image(p1), _register_image(p2), _register_image(p3)

    ca = DuplicateCandidate(source_path=str(p1), image_id=id1, sha256=sha)
    cb = DuplicateCandidate(source_path=str(p2), image_id=id2, sha256=sha)
    cc = DuplicateCandidate(source_path=str(p3), image_id=id3, sha256=sha)

    engine = DuplicateEngine()
    engine.process_candidates([ca, cb, cc])

    stats = engine.statistics
    assert stats.processed == 3
    assert stats.exact_duplicates >= 1
    assert stats.duplicates_found >= 1
    assert stats.elapsed_seconds >= 0.0
