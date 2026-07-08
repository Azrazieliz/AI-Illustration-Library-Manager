from __future__ import annotations

from time import monotonic, sleep

import pytest

from engine.adaptive_learning import (
    AdaptiveCandidate,
    AdaptiveEvidence,
    AdaptiveLearningBuilder,
    AdaptiveLearningEngine,
    AdaptiveLearningService,
    AdaptiveLearningSource,
    AdaptiveLearningWorker,
    AdaptivePersistenceCorruptionError,
)


def _wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if condition():
            return
        sleep(0.01)
    raise AssertionError("Timed out waiting for condition")


def _evidence(
    *,
    source: AdaptiveLearningSource,
    character_id: str,
    series_id: str,
    confidence: float,
    accepted: bool = False,
    rejected: bool = False,
    false_positive: bool = False,
    false_negative: bool = False,
    alias: str | None = None,
    relationship: tuple[str, str] | None = None,
    embedding_key: str | None = None,
) -> AdaptiveEvidence:
    return AdaptiveEvidence(
        source=source,
        canonical_character_id=character_id,
        canonical_series_id=series_id,
        confidence=confidence,
        accepted=accepted,
        rejected=rejected,
        false_positive=false_positive,
        false_negative=false_negative,
        embedding_key=embedding_key,
        embedding_vector=[0.1, 0.2] if embedding_key else [],
        visual_fingerprint="vf-1",
        filename_pattern="name-pattern",
        folder_pattern="folder-pattern",
        aliases=[alias] if alias else [],
        pose="standing",
        hairstyle="short",
        clothing="uniform",
        dominant_palette="#112233",
        accessories=["ribbon"],
        co_occurring_characters=["friend-1"],
        co_occurring_series=[series_id],
        relationships=[relationship] if relationship else [],
        knowledge_pack_confidence=0.8,
        embedding_similarity=0.75,
        filename_similarity=0.7,
        folder_similarity=0.65,
        series_probability=0.6,
        ambiguity=0.8,
        rare_character=True,
        unseen_alias=True,
    )


def test_incremental_learning_and_persistence() -> None:
    engine = AdaptiveLearningEngine()
    result = engine.incremental_train(
        [
            _evidence(
                source=AdaptiveLearningSource.APPROVED_REVIEW,
                character_id="char:a",
                series_id="series:x",
                confidence=0.9,
                accepted=True,
                alias="AliasA",
                embedding_key="emb:a",
            )
        ]
    )
    persisted = engine.persist()

    assert result.success is True
    assert isinstance(persisted, bytes)
    reloaded = AdaptiveLearningEngine()
    assert reloaded.load(persisted).success is True
    profile = reloaded.profile_for(canonical_character_id="char:a", canonical_series_id="series:x")
    assert profile.accepted_matches == 1


def test_rollback() -> None:
    engine = AdaptiveLearningEngine()
    engine.ingest_evidence(
        _evidence(
            source=AdaptiveLearningSource.APPROVED_REVIEW,
            character_id="char:r",
            series_id="series:r",
            confidence=0.8,
            accepted=True,
        )
    )
    engine.ingest_evidence(
        _evidence(
            source=AdaptiveLearningSource.REJECTED_REVIEW,
            character_id="char:r",
            series_id="series:r",
            confidence=0.2,
            rejected=True,
        )
    )
    rolled = engine.rollback()
    profile = engine.profile_for(canonical_character_id="char:r", canonical_series_id="series:r")

    assert rolled.success is True
    assert profile.accepted_matches == 1
    assert profile.rejected_matches == 0


def test_checkpointing_cancellation_and_resume() -> None:
    worker = AdaptiveLearningWorker(service=AdaptiveLearningService())
    worker.start()
    worker.pause()
    job_id = worker.submit_incremental_training(
        [
            _evidence(
                source=AdaptiveLearningSource.APPROVED_REVIEW,
                character_id="char:w",
                series_id="series:w",
                confidence=0.7,
                accepted=True,
            )
        ],
        idle_only=True,
    )
    worker.cancel(job_id)
    worker.resume()
    worker.set_idle(True)

    _wait_for(lambda: worker.checkpoint_for(job_id) is not None and worker.checkpoint_for(job_id).status.value == "cancelled")
    assert worker.resume_job(job_id) is True

    _wait_for(lambda: worker.checkpoint_for(job_id) is not None and worker.checkpoint_for(job_id).status.value == "completed")
    cp = worker.checkpoint_for(job_id)
    assert cp is not None
    assert cp.processed_events == 1
    worker.stop()


def test_cache_invalidation_and_confidence_improvement() -> None:
    engine = AdaptiveLearningEngine()
    candidate = AdaptiveCandidate(
        canonical_character_id="char:c",
        canonical_series_id="series:c",
        canonical_name="C",
        base_confidence=0.4,
        features={
            "embedding_similarity": 0.4,
            "filename_similarity": 0.4,
            "knowledge_pack_confidence": 0.5,
            "relationship_graph": 0.4,
            "series_probability": 0.4,
        },
    )

    before, best_before = engine.score_candidates(candidates=[candidate], series_hint="series:c")
    engine.ingest_evidence(
        _evidence(
            source=AdaptiveLearningSource.APPROVED_REVIEW,
            character_id="char:c",
            series_id="series:c",
            confidence=0.95,
            accepted=True,
        )
    )
    after, best_after = engine.score_candidates(candidates=[candidate], series_hint="series:c")

    assert best_before is not None and best_after is not None
    assert before[0].score <= after[0].score


def test_relationship_learning_and_identical_name_disambiguation() -> None:
    engine = AdaptiveLearningEngine()
    engine.ingest_evidence(
        _evidence(
            source=AdaptiveLearningSource.APPROVED_REVIEW,
            character_id="char:elizabeth",
            series_id="series:sds",
            confidence=0.92,
            accepted=True,
            relationship=("char:elizabeth", "char:meliodas"),
        )
    )

    candidates = [
        AdaptiveCandidate(
            canonical_character_id="char:elizabeth",
            canonical_series_id="series:sds",
            canonical_name="Elizabeth",
            base_confidence=0.5,
            features={"relationship_graph": 0.9, "series_probability": 0.9, "knowledge_pack_confidence": 0.8},
        ),
        AdaptiveCandidate(
            canonical_character_id="char:elizabeth",
            canonical_series_id="series:eis",
            canonical_name="Elizabeth",
            base_confidence=0.5,
            features={"relationship_graph": 0.2, "series_probability": 0.2, "knowledge_pack_confidence": 0.3},
        ),
    ]

    _, best = engine.score_candidates(candidates=candidates, series_hint="series:sds")
    profile = engine.profile_for(canonical_character_id="char:elizabeth", canonical_series_id="series:sds")

    assert best is not None
    assert best.canonical_series_id == "series:sds"
    assert any(key.startswith("char:elizabeth->char:meliodas") for key in profile.relationship_graph)


def test_knowledge_pack_and_external_db_learning_sources() -> None:
    engine = AdaptiveLearningEngine()
    engine.ingest_evidence(
        _evidence(
            source=AdaptiveLearningSource.KNOWLEDGE_PACK_UPDATE,
            character_id="char:k",
            series_id="series:k",
            confidence=0.85,
            accepted=True,
        )
    )
    engine.ingest_evidence(
        _evidence(
            source=AdaptiveLearningSource.EXTERNAL_CANONICAL_DATABASE,
            character_id="char:k",
            series_id="series:k",
            confidence=0.9,
            accepted=True,
        )
    )

    profile = engine.profile_for(canonical_character_id="char:k", canonical_series_id="series:k")
    assert profile.accepted_matches == 2


def test_duplicate_embedding_prevention() -> None:
    engine = AdaptiveLearningEngine()
    first = _evidence(
        source=AdaptiveLearningSource.APPROVED_REVIEW,
        character_id="char:e",
        series_id="series:e",
        confidence=0.8,
        accepted=True,
        embedding_key="dup-1",
    )
    second = _evidence(
        source=AdaptiveLearningSource.APPROVED_REVIEW,
        character_id="char:e",
        series_id="series:e",
        confidence=0.81,
        accepted=True,
        embedding_key="dup-1",
    )
    engine.ingest_evidence(first)
    engine.ingest_evidence(second)

    # Duplicate key is ignored for cache growth.
    assert len(engine._embedding_cache) == 1


def test_corruption_recovery_and_compressed_persistence() -> None:
    engine = AdaptiveLearningEngine()
    engine.ingest_evidence(
        _evidence(
            source=AdaptiveLearningSource.APPROVED_REVIEW,
            character_id="char:z",
            series_id="series:z",
            confidence=0.88,
            accepted=True,
        )
    )
    payload = engine.persist()
    assert len(payload) > 0

    with pytest.raises(AdaptivePersistenceCorruptionError):
        engine.load(b"not-valid-compressed-state")

    recovered = engine.recover_from_corruption()
    assert recovered.success is True
    assert engine.snapshot_statistics().active_profiles == 0


def test_statistics_and_uncertainty_queue() -> None:
    engine = AdaptiveLearningEngine()
    engine.incremental_train(
        [
            _evidence(
                source=AdaptiveLearningSource.APPROVED_REVIEW,
                character_id="char:s1",
                series_id="series:s",
                confidence=0.9,
                accepted=True,
                alias="seen",
            ),
            _evidence(
                source=AdaptiveLearningSource.REJECTED_REVIEW,
                character_id="char:s2",
                series_id="series:s",
                confidence=0.2,
                rejected=True,
            ),
        ]
    )
    queue = engine.active_learning_queue(limit=10)
    stats = engine.snapshot_statistics()

    assert len(queue) >= 2
    assert stats.learning_iterations >= 2
    assert stats.accepted_samples == 1
    assert stats.rejected_samples == 1
    assert stats.uncertainty_queue_size >= 2


def test_builder_roundtrip() -> None:
    builder = AdaptiveLearningBuilder()
    engine = AdaptiveLearningEngine(builder=builder)
    engine.ingest_evidence(
        _evidence(
            source=AdaptiveLearningSource.MANUAL_CHARACTER_CORRECTION,
            character_id="char:b",
            series_id="series:b",
            confidence=0.77,
            accepted=True,
        )
    )
    payload = engine.persist()
    profiles, uncertainty = builder.deserialize_state(payload)

    assert profiles
    assert uncertainty
