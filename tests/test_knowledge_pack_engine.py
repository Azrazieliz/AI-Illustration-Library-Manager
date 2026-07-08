from __future__ import annotations

from time import monotonic, sleep

import pytest

from engine.knowledge_packs import (
    KnowledgeEntry,
    KnowledgePackBuilder,
    KnowledgePackCompression,
    KnowledgePackConflictError,
    KnowledgePackDependencyError,
    KnowledgePackDomain,
    KnowledgePackEngine,
    KnowledgePackIntegrityError,
    KnowledgePackManifest,
    KnowledgePackService,
    KnowledgePackStorageLimitError,
    KnowledgePackValidationError,
    KnowledgePackWorker,
)
from engine.knowledge_packs.knowledge_pack_models import KnowledgePackTaskStatus


def _entry(canonical_id: str, name: str, *, alias: str | None = None, localized_ja: str | None = None) -> KnowledgeEntry:
    aliases = [alias] if alias else []
    localized = {"ja": localized_ja} if localized_ja else {}
    return KnowledgeEntry(
        canonical_id=canonical_id,
        canonical_name=name,
        aliases=aliases,
        localized_names=localized,
        tags=["hero"],
        categories=["character"],
    )


def _manifest(
    *,
    pack_id: str,
    version: str,
    domain: KnowledgePackDomain = KnowledgePackDomain.ANIME,
    priority: int = 0,
    dependencies: list[str] | None = None,
    entries: list[KnowledgeEntry] | None = None,
    incremental_from: str | None = None,
    installed_size_bytes: int = 1024,
    compression: KnowledgePackCompression = KnowledgePackCompression.GZIP,
) -> KnowledgePackManifest:
    builder = KnowledgePackBuilder()
    data = KnowledgePackManifest(
        pack_id=pack_id,
        version=version,
        domain=domain,
        author="maintainer",
        source="https://example.org/packs",
        checksum="",
        signature=f"sig:{pack_id}:{version}",
        compression=compression,
        metadata={"format": "canonical-db"},
        dependencies=list(dependencies or []),
        priority=priority,
        incremental_from=incremental_from,
        installed_size_bytes=installed_size_bytes,
        compressed_size_bytes=max(1, installed_size_bytes // 3),
        enabled=True,
        entries=list(entries or [_entry(f"{pack_id}:001", f"Name-{pack_id}")]),
    )
    data.checksum = builder.compute_checksum(data)
    return data


def _wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if condition():
            return
        sleep(0.01)
    raise AssertionError("Timed out waiting for condition")


def test_install_and_verify_pack() -> None:
    engine = KnowledgePackEngine()
    manifest = _manifest(pack_id="anime.core", version="1.0.0")
    result = engine.install_pack(manifest)

    assert result.success is True
    assert engine.verify_pack("anime.core").success is True


def test_uninstall_pack() -> None:
    engine = KnowledgePackEngine()
    engine.install_pack(_manifest(pack_id="manga.core", version="1.0.0", domain=KnowledgePackDomain.MANGA))
    result = engine.uninstall_pack("manga.core")

    assert result.success is True
    assert engine.list_installed() == []


def test_enable_and_disable_pack() -> None:
    engine = KnowledgePackEngine()
    engine.install_pack(_manifest(pack_id="vn.core", version="1.0.0", domain=KnowledgePackDomain.VISUAL_NOVEL))

    engine.disable_pack("vn.core")
    assert [item.pack_id for item in engine.list_enabled()] == []

    engine.enable_pack("vn.core")
    assert [item.pack_id for item in engine.list_enabled()] == ["vn.core"]


def test_update_and_version_migration() -> None:
    engine = KnowledgePackEngine()
    base = _manifest(pack_id="game.core", version="1.0.0", domain=KnowledgePackDomain.GAME)
    updated = _manifest(
        pack_id="game.core",
        version="1.1.0",
        domain=KnowledgePackDomain.GAME,
        incremental_from="1.0.0",
    )
    engine.install_pack(base)
    result = engine.update_pack(updated)

    assert result.success is True
    assert engine.list_installed()[0].version == "1.1.0"


def test_rollback_after_update() -> None:
    engine = KnowledgePackEngine()
    base = _manifest(pack_id="ln.core", version="1.0.0", domain=KnowledgePackDomain.LIGHT_NOVEL)
    updated = _manifest(
        pack_id="ln.core",
        version="1.0.1",
        domain=KnowledgePackDomain.LIGHT_NOVEL,
        incremental_from="1.0.0",
    )
    engine.install_pack(base)
    engine.update_pack(updated)
    result = engine.rollback_pack("ln.core")

    assert result.success is True
    assert engine.list_installed()[0].version == "1.0.0"


def test_dependency_resolution() -> None:
    engine = KnowledgePackEngine()
    dependent = _manifest(
        pack_id="anime.extension",
        version="1.0.0",
        dependencies=["anime.core"],
    )
    with pytest.raises(KnowledgePackDependencyError):
        engine.install_pack(dependent)

    engine.install_pack(_manifest(pack_id="anime.core", version="1.0.0"))
    assert engine.install_pack(dependent).success is True


def test_conflict_detection_respects_priority() -> None:
    engine = KnowledgePackEngine()
    high = _manifest(
        pack_id="core.high",
        version="1.0.0",
        priority=10,
        entries=[_entry("char:shared", "Hero")],
    )
    low = _manifest(
        pack_id="core.low",
        version="1.0.0",
        priority=1,
        entries=[_entry("char:shared", "HeroAlt")],
    )
    engine.install_pack(high)
    with pytest.raises(KnowledgePackConflictError):
        engine.install_pack(low)


def test_integrity_and_checksum_verification() -> None:
    engine = KnowledgePackEngine()
    broken = _manifest(pack_id="manhwa.core", version="1.0.0", domain=KnowledgePackDomain.MANHWA)
    broken.checksum = "deadbeef"

    with pytest.raises(KnowledgePackIntegrityError):
        engine.install_pack(broken)


def test_merge_packs() -> None:
    engine = KnowledgePackEngine()
    left = _manifest(
        pack_id="merge.left",
        version="1.0.0",
        entries=[_entry("char:left", "Left")],
    )
    right = _manifest(
        pack_id="merge.right",
        version="1.0.0",
        entries=[_entry("char:right", "Right")],
    )
    engine.install_pack(left)
    engine.install_pack(right)
    result = engine.merge_packs(
        target_pack_id="merge.left",
        source_pack_ids=["merge.right"],
        merged_pack_id="merge.all",
        version="1.0.0",
        author="maintainer",
        source="https://example.org/merge",
    )

    assert result.success is True
    ids = sorted(entry.canonical_id for entry in engine.repository.get_pack("merge.all").entries)
    assert ids == ["char:left", "char:right"]


def test_lookup_across_alias_and_localized_names() -> None:
    engine = KnowledgePackEngine()
    manifest = _manifest(
        pack_id="lookup.core",
        version="1.0.0",
        entries=[_entry("char:alpha", "Alpha", alias="A", localized_ja="Arufa")],
    )
    engine.install_pack(manifest)

    alias_hit = engine.lookup("A")
    locale_hit = engine.lookup("Arufa", locale="ja")

    assert alias_hit is not None
    assert alias_hit.canonical_id == "char:alpha"
    assert locale_hit is not None
    assert locale_hit.pack_id == "lookup.core"


def test_semver_duplicate_validation_and_checksum_helpers() -> None:
    builder = KnowledgePackBuilder()
    duplicate_manifest = _manifest(
        pack_id="dup.core",
        version="1.0.0",
        entries=[_entry("char:dup", "One"), _entry("char:dup", "Two")],
    )
    engine = KnowledgePackEngine()
    with pytest.raises(KnowledgePackValidationError):
        engine.install_pack(duplicate_manifest)

    assert builder.compare_semver("1.2.0", "1.1.9") > 0


def test_compression_roundtrip() -> None:
    builder = KnowledgePackBuilder()
    payload = b"knowledge-pack-payload"
    compressed = builder.compress_payload(payload, KnowledgePackCompression.GZIP)
    restored = builder.decompress_payload(compressed, KnowledgePackCompression.GZIP)

    assert restored == payload


def test_storage_limit_enforced() -> None:
    engine = KnowledgePackEngine()
    huge = _manifest(pack_id="huge.core", version="1.0.0", installed_size_bytes=(6 * 1024 * 1024 * 1024))
    with pytest.raises(KnowledgePackStorageLimitError):
        engine.install_pack(huge)


def test_worker_install_and_uninstall_flow() -> None:
    worker = KnowledgePackWorker(service=KnowledgePackService())
    worker.start()
    install_job = worker.submit_install(_manifest(pack_id="worker.core", version="1.0.0"))
    _wait_for(lambda: worker.checkpoint_for(install_job) is not None and worker.checkpoint_for(install_job).status == KnowledgePackTaskStatus.COMPLETED)
    uninstall_job = worker.submit_uninstall("worker.core")
    _wait_for(lambda: worker.checkpoint_for(uninstall_job) is not None and worker.checkpoint_for(uninstall_job).status == KnowledgePackTaskStatus.COMPLETED)

    assert worker.result_for(install_job) is not None
    assert worker.result_for(uninstall_job) is not None
    worker.stop()


def test_worker_cancellation_and_resume() -> None:
    worker = KnowledgePackWorker(service=KnowledgePackService())
    worker.start()
    worker.pause()
    job_id = worker.submit_install(_manifest(pack_id="resume.core", version="1.0.0", domain=KnowledgePackDomain.CUSTOM))
    worker.cancel(job_id)
    worker.resume()
    _wait_for(lambda: worker.checkpoint_for(job_id) is not None and worker.checkpoint_for(job_id).status == KnowledgePackTaskStatus.CANCELLED)

    resumed = worker.resume_job(job_id)
    assert resumed is True
    _wait_for(lambda: worker.checkpoint_for(job_id) is not None and worker.checkpoint_for(job_id).status == KnowledgePackTaskStatus.COMPLETED)

    progress = worker.progress_for(job_id)
    assert progress is not None
    assert progress.progress == 100
    worker.stop()
