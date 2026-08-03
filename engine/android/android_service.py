from __future__ import annotations

from dataclasses import asdict, is_dataclass
from collections.abc import Iterable
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
import json
import os
import traceback
from threading import Lock

from engine.android.android_exceptions import AndroidStorageError
from engine.android.android_models import (
    AndroidCharacter,
    AndroidCollection,
    AndroidImage,
    AndroidJob,
    AndroidSearchResult,
    AndroidSeries,
    AndroidSettings,
)
from engine.android.android_statistics import AndroidStatisticsTracker
from engine.android.android_worker import AndroidWorker
from engine.automation.automation_service import AutomationService
from engine.bulk.bulk_service import BulkService
from engine.character_database.character_database_service import CharacterDatabaseService
from engine.collections.collection_service import CollectionService
from engine.export.export_service import ExportService
from engine.library.library_service import LibraryService
from engine.organizer.organizer_service import OrganizerService
from engine.pipeline import PipelineJob, QueueType
from engine.plugin_system import PluginService
from engine.recognition.recognition_service import RecognitionService
from engine.rename.rename_service import RenameService
from engine.review.review_service import ReviewService
from engine.scanner.scanner_service import ScannerService
from engine.search.search_service import SearchService
from engine.search_advanced.search_service import AdvancedSearchService
from engine.knowledge_packs import KnowledgePackService
from engine.review.review_models import ReviewStatus
from engine.services.job_service import JobService
from engine.services.tag_service import TagService
from engine.logging import get_logger


class AndroidStorageAdapter(Protocol):
    scheme: str

    def resolve(self, uri: str) -> str: ...


class ScopedStorageAdapter(AndroidStorageAdapter, Protocol):
    def resolve_tree_uri(self, uri: str) -> str: ...


class SAFAdapter(AndroidStorageAdapter, Protocol):
    pass


class MediaStoreAdapter(AndroidStorageAdapter, Protocol):
    pass


class DocumentProviderAdapter(AndroidStorageAdapter, Protocol):
    pass


class NASAdapter(AndroidStorageAdapter, Protocol):
    pass


class SMBAdapter(AndroidStorageAdapter, Protocol):
    pass


class FTPAdapter(AndroidStorageAdapter, Protocol):
    pass


class SFTPAdapter(AndroidStorageAdapter, Protocol):
    pass


class WebDAVAdapter(AndroidStorageAdapter, Protocol):
    pass


class CloudProviderAdapter(AndroidStorageAdapter, Protocol):
    pass


class AndroidService:
    """Adapter-only service that exposes existing engine capabilities to Android callers."""

    def __init__(
        self,
        *,
        scanner_service: ScannerService | Any | None = None,
        recognition_service: RecognitionService | Any | None = None,
        rename_service: RenameService | Any | None = None,
        organizer_service: OrganizerService | Any | None = None,
        search_service: SearchService | Any | None = None,
        advanced_search_service: AdvancedSearchService | Any | None = None,
        collection_service: CollectionService | Any | None = None,
        character_database_service: CharacterDatabaseService | Any | None = None,
        tag_service: TagService | Any | None = None,
        bulk_service: BulkService | Any | None = None,
        job_service: JobService | Any | None = None,
        automation_service: AutomationService | Any | None = None,
        export_service: ExportService | Any | None = None,
        library_service: LibraryService | Any | None = None,
        review_service: ReviewService | Any | None = None,
        knowledge_pack_service: KnowledgePackService | Any | None = None,
        plugin_service: PluginService | Any | None = None,
        worker: AndroidWorker | None = None,
        statistics: AndroidStatisticsTracker | None = None,
        settings: AndroidSettings | None = None,
    ) -> None:
        self.scanner_service = scanner_service or ScannerService()
        self.recognition_service = recognition_service or RecognitionService()
        self.rename_service = rename_service or RenameService()
        self.organizer_service = organizer_service or OrganizerService()
        self.search_service = search_service or SearchService()
        self.advanced_search_service = advanced_search_service or AdvancedSearchService()
        self.collection_service = collection_service or CollectionService()
        self.character_database_service = character_database_service or CharacterDatabaseService()
        self.tag_service = tag_service or TagService()
        self.bulk_service = bulk_service or BulkService()
        self.job_service = job_service or JobService()
        self.automation_service = automation_service or AutomationService()
        self.export_service = export_service or ExportService()
        self.library_service = library_service or LibraryService()
        self.review_service = review_service or ReviewService()
        self.knowledge_pack_service = knowledge_pack_service or KnowledgePackService()
        self.plugin_service = plugin_service or PluginService()
        self.worker = worker or AndroidWorker()
        self.statistics = statistics or AndroidStatisticsTracker()
        self.settings = settings or AndroidSettings()
        self.logger = get_logger(self.__class__.__name__)

        self._thumbnail_cache: dict[str, bytes] = {}
        self._memory_trimming_hooks: list[Any] = []
        self._storage_adapters: dict[str, AndroidStorageAdapter] = {}
        self._scan_lock = Lock()
        self._scan_state: dict[str, Any] = {
            "status": "idle",
            "root": None,
            "discovered_images": 0,
            "current_file": None,
            "job_id": None,
            "error": None,
            "exception_message": None,
            "exception_traceback": None,
        }

    def scan_library(self, root: str) -> list[AndroidImage]:
        discovered = self.scanner_service.scan(Path(root))
        return [
            AndroidImage(image_id=0, path=str(path), filename=Path(path).name)
            for path in discovered
        ]

    def start_scan(self, root: str) -> AndroidJob:
        root_path = str(root).strip()
        if not root_path:
            raise AndroidStorageError("scan root is required")

        with self._scan_lock:
            if self._scan_state["status"] in {"running", "paused"}:
                existing = self.worker.get_job(str(self._scan_state["job_id"]))
                if existing is not None:
                    return existing

            self._scan_state = {
                "status": "running",
                "root": root_path,
                "discovered_images": 0,
                "current_file": None,
                "job_id": "scan-library",
                "error": None,
                "exception_message": None,
                "exception_traceback": None,
            }

        def _scan_action() -> int:
            count = 0
            try:
                if "://" in root_path:
                    raise ValueError(
                        "Unsupported scan root URI. "
                        "Provide a filesystem path accessible to the backend process, "
                        f"but received: {root_path}"
                    )

                for path in self.scanner_service.scan(Path(root_path)):
                    count += 1
                    with self._scan_lock:
                        self._scan_state["discovered_images"] = count
                        self._scan_state["current_file"] = str(path)
                    # Indeterminate progress; keep it moving until completion.
                    progress = min(99.0, 5.0 + float(count) * 2.0)
                    self.worker.report_progress(
                        "scan-library",
                        progress,
                        message=f"Scanning... {count} images discovered",
                    )
                with self._scan_lock:
                    self._scan_state["status"] = "completed"
                self.worker.report_progress("scan-library", 100.0, message=f"Scan completed: {count} images")
                return count
            except Exception as exc:
                traceback_text = traceback.format_exc()
                self.logger.exception("Scan job failed", extra={"root": root_path})
                with self._scan_lock:
                    self._scan_state["status"] = "failed"
                    self._scan_state["error"] = str(exc)
                    self._scan_state["exception_message"] = str(exc)
                    self._scan_state["exception_traceback"] = traceback_text
                raise

        return self.worker.submit(job_id="scan-library", action=_scan_action)

    def pause_scan(self) -> bool:
        self.scanner_service.pause_scan()
        with self._scan_lock:
            if self._scan_state["status"] == "running":
                self._scan_state["status"] = "paused"
        return True

    def resume_scan(self) -> bool:
        self.scanner_service.resume_scan()
        with self._scan_lock:
            if self._scan_state["status"] == "paused":
                self._scan_state["status"] = "running"
        return True

    def cancel_scan(self) -> bool:
        self.scanner_service.cancel_scan()
        cancelled = self.worker.cancel("scan-library")
        with self._scan_lock:
            self._scan_state["status"] = "cancelled"
        return cancelled

    def scan_status(self) -> dict[str, Any]:
        with self._scan_lock:
            status = dict(self._scan_state)
        job = self.worker.get_job("scan-library")
        if job is not None:
            status["progress"] = job.progress
            if job.message and not status.get("exception_message"):
                status["exception_message"] = job.message
            if status.get("status") != "failed" and job.status == "failed":
                status["status"] = "failed"
                status["error"] = status.get("error") or job.message
                status["exception_message"] = status.get("exception_message") or job.message
            if status.get("status") not in {"completed", "failed", "cancelled"}:
                status["status"] = job.status
        else:
            status["progress"] = 0.0
        status["error"] = status.get("error") or status.get("exception_message")
        if not self._is_debug_mode():
            status.pop("exception_traceback", None)
        else:
            status["traceback"] = status.get("exception_traceback")
        return status

    @staticmethod
    def _is_debug_mode() -> bool:
        return os.getenv("AILM_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

    def recognize_image(self, path: str) -> dict[str, Any] | None:
        self.statistics.record_recognition_request()
        result = self.recognition_service.process_recognition_job(
            PipelineJob(source_path=path, queue_type=QueueType.RECOGNITION),
        )
        if result is None:
            return None
        return result.output.to_dict() if hasattr(result.output, "to_dict") else result.output.__dict__

    def rename_image(self, path: str, *, dry_run: bool = False, rule: Any | None = None) -> Any:
        return self.rename_service.apply_rename([path], dry_run=dry_run, rule=rule)

    def organize_image(self, path: str, *, dry_run: bool = False, rules: list[Any] | None = None) -> Any:
        return self.organizer_service.apply_organize([path], dry_run=dry_run, rules=rules)

    def search(self, *, query_vector: list[float], top_k: int = 10, min_similarity: float = 0.0) -> list[AndroidSearchResult]:
        self.statistics.record_search_request()
        response = self.search_service.query(
            query_vector=query_vector,
            top_k=top_k,
            min_similarity=min_similarity,
        )
        return [
            AndroidSearchResult(
                image_id=match.image_id,
                path=str(match.path),
                score=match.similarity,
                metadata=dict(match.metadata),
            )
            for match in response.matches
        ]

    def advanced_search(self, *, action: str = "search", payload: dict[str, Any] | None = None) -> Any:
        metadata = {"stage": "advanced_search", "action": action}
        if payload:
            metadata.update(payload)
        return self.advanced_search_service.process_advanced_search_job(
            PipelineJob(queue_type=QueueType.SEARCH, metadata=metadata),
        )

    def semantic_search(self, *, query_vector: list[float], top_k: int = 10, min_similarity: float = 0.0) -> list[AndroidSearchResult]:
        return self.search(query_vector=query_vector, top_k=top_k, min_similarity=min_similarity)

    def list_library_images(
        self,
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int = 200,
    ) -> list[AndroidImage]:
        records = list(self.library_service.list_images())

        if query:
            term = query.strip().lower()
            if term:
                filtered: list[Any] = []
                for item in records:
                    payload = self._object_to_dict(item)
                    path = str(payload.get("original_path") or payload.get("path") or payload.get("file_path") or "")
                    filename = str(payload.get("filename") or (Path(path).name if path else ""))
                    metadata_text = str(payload.get("metadata", "")).lower()
                    if term in path.lower() or term in filename.lower() or term in metadata_text:
                        filtered.append(item)
                records = filtered

        def sort_key(item: Any) -> str:
            payload = self._object_to_dict(item)
            return str(payload.get("original_path") or payload.get("path") or "").lower()

        records.sort(key=sort_key)
        page = max(page, 1)
        page_size = max(page_size, 1)
        start = (page - 1) * page_size
        return [self._to_android_image(item) for item in records[start : start + page_size]]
    def get_collections(self, *, query: str | None = None, page: int = 1, page_size: int = 50) -> list[AndroidCollection]:
        if query:
            results = self.collection_service.search_collections(query)
            collections = [
                AndroidCollection(
                    collection_id=result.collection_id,
                    name=result.name,
                    kind="search",
                    image_count=0,
                    metadata={"score": result.score, "reason": result.reason},
                )
                for result in results
            ]
        else:
            collections = []
            for node in self.collection_service.hierarchy():
                self._append_collection_hierarchy(collections, node)
        return self._paginate(collections, page=page, page_size=page_size)

    def get_character(self, identifier: int | str) -> AndroidCharacter | None:
        record = self.character_database_service.lookup_character(identifier)
        if record is None:
            return None
        return AndroidCharacter(
            character_id=record.character_id,
            canonical_name=record.canonical_name,
            series_id=record.series_id,
            aliases=list(record.aliases),
        )

    def get_series(self, identifier: int | str) -> AndroidSeries | None:
        record = self.character_database_service.lookup_series(identifier)
        if record is None:
            return None
        return AndroidSeries(
            series_id=record.series_id,
            canonical_title=record.canonical_title,
            aliases=list(record.aliases),
        )

    def get_tags(self) -> list[str]:
        return [tag.name for tag in self.tag_service.list_tags()]

    def start_bulk_operation(self, operation: str, **kwargs: Any) -> AndroidJob:
        operation_key = operation.strip().lower()
        if operation_key == "rename":
            result = self.bulk_service.rename_images(**kwargs)
        elif operation_key == "organize":
            result = self.bulk_service.organize_images(**kwargs)
        elif operation_key == "copy":
            result = self.bulk_service.copy_images(**kwargs)
        elif operation_key == "move":
            result = self.bulk_service.move_images(**kwargs)
        elif operation_key == "delete":
            result = self.bulk_service.delete_images(**kwargs)
        else:
            result = self.bulk_service.assign_tags(**kwargs)
        return AndroidJob(
            job_id=str(result.batch_id),
            status=str(result.status.value),
            progress=float(result.progress_percentage),
            metadata={"operation": operation_key},
        )

    def get_jobs(self) -> list[AndroidJob]:
        jobs = [
            AndroidJob(
                job_id=str(job.id),
                status=job.status,
                progress=float(job.progress),
            )
            for job in self.job_service.list_running_jobs()
        ]
        worker_jobs = self.worker.running_jobs()
        jobs.extend(worker_jobs)
        self.statistics.set_running_jobs(len(jobs))
        return jobs

    def cancel_job(self, job_id: str) -> bool:
        return self.worker.cancel(job_id)

    def resume_job(self, job_id: str) -> bool:
        return self.worker.resume(job_id)

    def pause_automation(self, job_id: str | None = None) -> Any:
        if job_id:
            return self.automation_service.engine.pause(job_id)
        self.worker.on_low_memory(2)
        return True

    def resume_automation(self, job_id: str | None = None) -> Any:
        if job_id:
            return self.automation_service.engine.resume(job_id)
        return True

    def export_dataset(self, source_path: str, *, metadata: dict[str, Any] | None = None) -> Any:
        job = PipelineJob(
            source_path=source_path,
            queue_type=QueueType.SEARCH,
            metadata={"stage": "export", **(metadata or {})},
        )
        return self.export_service.process_export_job(job)

    def library_statistics(self) -> dict[str, Any]:
        report = self.library_service.statistics()
        return self._object_to_dict(report)

    def health_status(self) -> dict[str, Any]:
        health = self.library_service.health()
        payload = self._object_to_dict(health)
        payload["android_supported_versions"] = list(self.settings.supported_android_versions)
        return payload

    def get_review_queue(self) -> list[dict[str, Any]]:
        items = self.review_service.filter_reviews(status=ReviewStatus.PENDING)
        return [self._object_to_dict(item) for item in items]

    def update_review(self, item_id: str, action: str, payload: dict[str, Any] | None = None) -> bool:
        payload = payload or {}
        action_key = action.strip().lower()
        if action_key == "undo":
            return self.review_service.rollback_last_batch() is not None

        try:
            review_id = int(item_id)
        except Exception:
            return False

        reviewer = payload.get("reviewer")
        reason = payload.get("reason")
        if action_key == "approve":
            _ = self.review_service.approve_review(review_id, reviewer=reviewer, reason=reason)
            return True
        if action_key == "reject":
            _ = self.review_service.reject_review(review_id, reviewer=reviewer, reason=reason)
            return True
        if action_key == "skip":
            _ = self.review_service.skip_review(review_id, reviewer=reviewer, reason=reason)
            return True
        return False

    def list_knowledge_packs(self) -> list[dict[str, Any]]:
        packs = self.knowledge_pack_service.engine.list_installed()
        return [self._object_to_dict(item) for item in packs]

    def list_plugins(self) -> list[dict[str, Any]]:
        runtimes = self.plugin_service.engine.repository.list_runtimes()
        return [self._object_to_dict(item) for item in runtimes]

    def list_downloads(self) -> list[dict[str, Any]]:
        release_root = Path("release") / "android"
        metadata_path = release_root / "release-metadata.json"
        if not metadata_path.exists():
            return []

        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        packaging = payload.get("android_packaging", {})
        out: list[dict[str, Any]] = []
        for kind in ("apk", "aab"):
            relative_path = packaging.get(kind)
            if not relative_path:
                continue
            artifact_path = Path(relative_path)
            if not artifact_path.is_absolute():
                artifact_path = Path.cwd() / artifact_path
            out.append(
                {
                    "type": kind,
                    "path": str(artifact_path),
                    "exists": artifact_path.exists(),
                }
            )
        return out

    def register_storage_adapter(self, adapter: AndroidStorageAdapter) -> None:
        self._storage_adapters[adapter.scheme] = adapter

    def resolve_uri(self, uri: str) -> str:
        scheme = self._extract_scheme(uri)
        adapter = self._storage_adapters.get(scheme)
        if adapter is None:
            raise AndroidStorageError(f"No adapter registered for scheme '{scheme}'")
        return adapter.resolve(uri)

    def cache_thumbnail(self, key: str, payload: bytes) -> None:
        self._thumbnail_cache[key] = payload
        self.statistics.set_cache_usage_bytes(sum(len(item) for item in self._thumbnail_cache.values()))

    def get_thumbnail(self, key: str) -> bytes | None:
        return self._thumbnail_cache.get(key)

    def trim_memory(self, level: int) -> None:
        if level >= 2:
            self._thumbnail_cache.clear()
            self.statistics.set_cache_usage_bytes(0)
        for hook in self._memory_trimming_hooks:
            hook(level)

    def register_memory_trimming_hook(self, hook: Any) -> None:
        self._memory_trimming_hooks.append(hook)

    def incremental_load(self, paths: Iterable[str], *, offset: int = 0, limit: int = 50) -> list[AndroidImage]:
        sliced = list(paths)[offset : offset + limit]
        return [
            AndroidImage(image_id=0, path=path, filename=Path(path).name)
            for path in sliced
        ]

    def run_background_task(self, *, job_id: str, action: Any, args: tuple[Any, ...] = (), kwargs: dict[str, Any] | None = None, checkpoint: str | None = None) -> AndroidJob:
        started = perf_counter()
        job = self.worker.submit(job_id=job_id, action=action, args=args, kwargs=kwargs, checkpoint=checkpoint)
        self.statistics.set_background_tasks(self.worker.background_task_count())
        self.statistics.record_bridge_call((perf_counter() - started) * 1000.0)
        return job
    def _to_android_image(self, image: Any) -> AndroidImage:
        payload = self._object_to_dict(image)

        raw_id = payload.get("id", payload.get("image_id", 0))
        try:
            image_id = int(raw_id or 0)
        except Exception:
            image_id = 0

        path = str(payload.get("original_path") or payload.get("path") or payload.get("file_path") or "")
        filename = str(payload.get("filename") or (Path(path).name if path else ""))
        if not filename:
            filename = f"Image {image_id}"

        thumbnail_path = payload.get("thumbnail_path")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "id",
                    "image_id",
                    "original_path",
                    "path",
                    "file_path",
                    "filename",
                    "thumbnail_path",
                    "metadata",
                    "_sa_instance_state",
                }
            }

        return AndroidImage(
            image_id=image_id,
            path=path,
            filename=filename,
            thumbnail_path=thumbnail_path,
            metadata=dict(metadata or {}),
        )
    def _append_collection_hierarchy(self, out: list[AndroidCollection], node: Any) -> None:
        out.append(
            AndroidCollection(
                collection_id=node.collection_id,
                name=node.name,
                kind=str(node.kind.value if hasattr(node.kind, "value") else node.kind),
                image_count=0,
            )
        )
        for child in getattr(node, "children", []):
            self._append_collection_hierarchy(out, child)

    def _paginate(self, items: list[Any], *, page: int, page_size: int) -> list[Any]:
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 1
        start = (page - 1) * page_size
        return items[start : start + page_size]

    def _extract_scheme(self, uri: str) -> str:
        if "://" in uri:
            return uri.split("://", 1)[0].lower()
        if ":" in uri:
            return uri.split(":", 1)[0].lower()
        return "file"

    def _object_to_dict(self, value: Any) -> dict[str, Any]:
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "__dict__"):
            data = dict(value.__dict__)
            data.pop("_sa_instance_state", None)
            return data
        slots = getattr(value, "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        out: dict[str, Any] = {}
        for key in slots:
            out[key] = getattr(value, key)
        return out
