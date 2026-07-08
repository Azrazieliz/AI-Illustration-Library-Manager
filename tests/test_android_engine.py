from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from engine.android import (
    AndroidBridge,
    AndroidCollection,
    AndroidImage,
    AndroidJob,
    AndroidSearchResult,
    AndroidService,
    AndroidSettings,
    AndroidWorker,
)
from engine.android.android_models import AndroidCharacter, AndroidSeries, AndroidStatistics
from engine.android.android_service import AndroidStorageAdapter


@dataclass(slots=True)
class _FakeMatch:
    image_id: int
    path: Path
    similarity: float
    metadata: dict[str, Any]


@dataclass(slots=True)
class _FakeSearchResponse:
    matches: list[_FakeMatch]


@dataclass(slots=True)
class _FakeBulkStatus:
    value: str


@dataclass(slots=True)
class _FakeBulkResult:
    batch_id: str
    status: _FakeBulkStatus
    progress_percentage: float


@dataclass(slots=True)
class _FakeTag:
    name: str


@dataclass(slots=True)
class _FakeCollectionNode:
    collection_id: int
    name: str
    kind: str
    children: list[Any]


@dataclass(slots=True)
class _FakeLibraryStats:
    total_images: int = 10
    total_tags: int = 3


@dataclass(slots=True)
class _FakeLibraryHealth:
    healthy: bool = True
    warnings: list[str] = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


class _FakeScannerService:
    def scan(self, root: Path) -> list[Path]:
        return [root / "a.png", root / "b.png"]


class _FakeRecognitionOutput:
    def to_dict(self) -> dict[str, Any]:
        return {"label": "character", "confidence": 0.99}


class _FakeRecognitionResult:
    def __init__(self) -> None:
        self.output = _FakeRecognitionOutput()


class _FakeRecognitionService:
    def process_recognition_job(self, job: Any) -> _FakeRecognitionResult:
        return _FakeRecognitionResult()


class _FakeRenameService:
    def apply_rename(self, paths: list[str], *, dry_run: bool, rule: Any) -> dict[str, Any]:
        return {"paths": list(paths), "dry_run": dry_run}


class _FakeOrganizerService:
    def apply_organize(self, paths: list[str], *, dry_run: bool, rules: list[Any] | None) -> dict[str, Any]:
        return {"paths": list(paths), "dry_run": dry_run, "rules": list(rules or [])}


class _FakeSearchService:
    def query(self, *, query_vector: list[float], top_k: int, min_similarity: float) -> _FakeSearchResponse:
        return _FakeSearchResponse(
            matches=[
                _FakeMatch(image_id=1, path=Path("/tmp/image.png"), similarity=0.95, metadata={"source": "test"})
            ]
        )


class _FakeAdvancedSearchService:
    def process_advanced_search_job(self, job: Any) -> dict[str, Any]:
        return {"ok": True, "action": job.metadata.get("action")}


class _FakeCollectionService:
    def search_collections(self, query: str) -> list[Any]:
        result = type("_R", (), {})
        item = result()
        item.collection_id = 2
        item.name = "Favorites"
        item.score = 0.8
        item.reason = "name-match"
        return [item]

    def hierarchy(self) -> list[Any]:
        child = _FakeCollectionNode(collection_id=2, name="Child", kind="static", children=[])
        root = _FakeCollectionNode(collection_id=1, name="Root", kind="static", children=[child])
        return [root]


class _FakeCharacterDatabaseService:
    def lookup_character(self, identifier: int | str) -> Any:
        character = type("_Character", (), {})
        result = character()
        result.character_id = 5
        result.canonical_name = "Alice"
        result.series_id = 10
        result.aliases = ["Al"]
        return result

    def lookup_series(self, identifier: int | str) -> Any:
        series = type("_Series", (), {})
        result = series()
        result.series_id = 10
        result.canonical_title = "Wonderland"
        result.aliases = ["WL"]
        return result


class _FakeTagService:
    def list_tags(self) -> list[_FakeTag]:
        return [_FakeTag(name="portrait"), _FakeTag(name="fantasy")]


class _FakeBulkService:
    def rename_images(self, **kwargs: Any) -> _FakeBulkResult:
        return _FakeBulkResult(batch_id="bulk-1", status=_FakeBulkStatus("running"), progress_percentage=42.0)

    def organize_images(self, **kwargs: Any) -> _FakeBulkResult:
        return _FakeBulkResult(batch_id="bulk-2", status=_FakeBulkStatus("running"), progress_percentage=10.0)

    def copy_images(self, **kwargs: Any) -> _FakeBulkResult:
        return _FakeBulkResult(batch_id="bulk-3", status=_FakeBulkStatus("running"), progress_percentage=5.0)

    def move_images(self, **kwargs: Any) -> _FakeBulkResult:
        return _FakeBulkResult(batch_id="bulk-4", status=_FakeBulkStatus("running"), progress_percentage=5.0)

    def delete_images(self, **kwargs: Any) -> _FakeBulkResult:
        return _FakeBulkResult(batch_id="bulk-5", status=_FakeBulkStatus("running"), progress_percentage=5.0)

    def assign_tags(self, **kwargs: Any) -> _FakeBulkResult:
        return _FakeBulkResult(batch_id="bulk-6", status=_FakeBulkStatus("running"), progress_percentage=5.0)


class _FakeJobService:
    def list_running_jobs(self) -> list[Any]:
        job_type = type("_Job", (), {})
        job = job_type()
        job.id = "job-db-1"
        job.status = "running"
        job.progress = 30
        return [job]


class _FakeAutomationEngine:
    def pause(self, job_id: str) -> dict[str, Any]:
        return {"paused": True, "job_id": job_id}

    def resume(self, job_id: str) -> dict[str, Any]:
        return {"resumed": True, "job_id": job_id}


class _FakeAutomationService:
    def __init__(self) -> None:
        self.engine = _FakeAutomationEngine()


class _FakeExportService:
    def process_export_job(self, job: Any) -> dict[str, Any]:
        return {"exported": True, "path": job.source_path}


class _FakeLibraryService:
    def statistics(self) -> _FakeLibraryStats:
        return _FakeLibraryStats()

    def health(self) -> _FakeLibraryHealth:
        return _FakeLibraryHealth()


class _ContentAdapter(AndroidStorageAdapter):
    scheme = "content"

    def resolve(self, uri: str) -> str:
        return "/resolved/content/path"


def _build_service(worker: AndroidWorker | None = None) -> AndroidService:
    return AndroidService(
        scanner_service=_FakeScannerService(),
        recognition_service=_FakeRecognitionService(),
        rename_service=_FakeRenameService(),
        organizer_service=_FakeOrganizerService(),
        search_service=_FakeSearchService(),
        advanced_search_service=_FakeAdvancedSearchService(),
        collection_service=_FakeCollectionService(),
        character_database_service=_FakeCharacterDatabaseService(),
        tag_service=_FakeTagService(),
        bulk_service=_FakeBulkService(),
        job_service=_FakeJobService(),
        automation_service=_FakeAutomationService(),
        export_service=_FakeExportService(),
        library_service=_FakeLibraryService(),
        worker=worker,
    )


def test_android_bridge_core_calls() -> None:
    worker = AndroidWorker(max_workers=1)
    service = _build_service(worker=worker)
    bridge = AndroidBridge(service=service)

    scanned = bridge.scanLibrary(".")
    searched = bridge.search(query_vector=[0.1, 0.2], top_k=1)
    advanced = bridge.advancedSearch(action="search", payload={"query": {"query_text": "hero"}})
    stats = bridge.libraryStatistics()
    health = bridge.healthStatus()

    assert len(scanned) == 2
    assert isinstance(scanned[0], AndroidImage)
    assert len(searched) == 1
    assert isinstance(searched[0], AndroidSearchResult)
    assert advanced["ok"] is True
    assert stats["total_images"] == 10
    assert health["healthy"] is True
    worker.shutdown()


def test_android_service_character_series_tags_and_collections() -> None:
    worker = AndroidWorker(max_workers=1)
    service = _build_service(worker=worker)

    character = service.get_character(5)
    series = service.get_series(10)
    tags = service.get_tags()
    collections = service.get_collections(page=1, page_size=10)

    assert isinstance(character, AndroidCharacter)
    assert isinstance(series, AndroidSeries)
    assert tags == ["portrait", "fantasy"]
    assert len(collections) == 2
    assert all(isinstance(item, AndroidCollection) for item in collections)
    worker.shutdown()


def test_android_dto_serialization_roundtrip() -> None:
    job = AndroidJob(job_id="job-1", status="running", progress=12.0)
    payload = job.to_dict()
    restored = AndroidJob.from_dict(payload)
    assert restored.job_id == "job-1"

    stats = AndroidStatistics(bridge_calls=3, searches=2)
    stats_restored = AndroidStatistics.from_dict(stats.to_dict())
    assert stats_restored.bridge_calls == 3


def test_android_worker_progress_and_checkpoint() -> None:
    worker = AndroidWorker(max_workers=1)
    progress_events: list[AndroidJob] = []
    gate = Event()

    def action() -> str:
        gate.wait(0.2)
        return "done"

    worker.register_progress_callback(progress_events.append)
    worker.submit(job_id="job-progress", action=action, checkpoint="cp-0")
    worker.report_progress("job-progress", 25.0, message="started", checkpoint="cp-1")
    gate.set()
    worker.shutdown()

    job = worker.get_job("job-progress")
    assert job is not None
    assert job.checkpoint == "cp-1"
    assert len(progress_events) >= 1


def test_android_worker_cancel_and_resume() -> None:
    worker = AndroidWorker(max_workers=1)
    gate = Event()

    def blocking() -> None:
        gate.wait(0.2)

    worker.submit(job_id="block", action=blocking)
    worker.submit(job_id="resumable", action=lambda: "ok")
    cancelled = worker.cancel("resumable")
    resumed = worker.resume("resumable")
    gate.set()
    worker.shutdown()

    assert cancelled is True
    assert resumed is True
    resumed_job = worker.get_job("resumable")
    assert resumed_job is not None
    assert resumed_job.status in {"completed", "running", "cancelled"}


def test_android_storage_adapter_and_uri_handling() -> None:
    worker = AndroidWorker(max_workers=1)
    service = _build_service(worker=worker)
    service.register_storage_adapter(_ContentAdapter())

    resolved = service.resolve_uri("content://images/123")

    assert resolved == "/resolved/content/path"
    worker.shutdown()


def test_android_scoped_storage_and_settings_compatibility() -> None:
    settings = AndroidSettings()
    restored = AndroidSettings.from_dict(settings.to_dict())
    assert restored.scoped_storage_enabled is True
    assert restored.future_jetpack_compose_ui is True
    assert restored.future_flutter_bridge is True
    assert restored.supported_android_versions == [11, 12, 13, 14, 15]


def test_android_thumbnail_cache_and_memory_trimming() -> None:
    worker = AndroidWorker(max_workers=1)
    service = _build_service(worker=worker)
    hook_calls: list[int] = []

    service.register_memory_trimming_hook(lambda level: hook_calls.append(level))
    service.cache_thumbnail("thumb-1", b"abc")
    assert service.get_thumbnail("thumb-1") == b"abc"

    service.trim_memory(2)

    assert service.get_thumbnail("thumb-1") is None
    assert hook_calls == [2]
    worker.shutdown()


def test_android_incremental_loading_and_pagination() -> None:
    worker = AndroidWorker(max_workers=1)
    service = _build_service(worker=worker)

    paths = [f"/tmp/{index}.png" for index in range(20)]
    page = service.incremental_load(paths, offset=5, limit=4)

    assert len(page) == 4
    assert page[0].filename == "5.png"
    worker.shutdown()


def test_android_background_execution_and_bridge_statistics() -> None:
    worker = AndroidWorker(max_workers=1)
    service = _build_service(worker=worker)

    service.run_background_task(job_id="bg-1", action=lambda: "ok")
    bridge = AndroidBridge(service=service)
    bridge.getJobs()

    snapshot = service.statistics.snapshot()
    worker.shutdown()

    assert snapshot.bridge_calls >= 1
    assert snapshot.running_jobs >= 1


def test_android_bridge_bulk_job_export_and_automation_controls() -> None:
    worker = AndroidWorker(max_workers=1)
    service = _build_service(worker=worker)
    bridge = AndroidBridge(service=service)

    bulk = bridge.startBulkOperation("rename", image_ids=[1], dry_run=True)
    exported = bridge.exportDataset("dataset/path")
    paused = bridge.pauseAutomation("job-123")
    resumed = bridge.resumeAutomation("job-123")

    assert bulk.job_id == "bulk-1"
    assert exported["exported"] is True
    assert paused["paused"] is True
    assert resumed["resumed"] is True
    worker.shutdown()
