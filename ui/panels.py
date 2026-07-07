from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.automation import AutomationService
from engine.bulk import BulkService
from engine.character_database import CharacterDatabaseService
from engine.collections import CollectionService
from engine.dataset import DatasetService
from engine.knowledge_base import KnowledgeBaseService
from engine.library import LibraryService
from engine.library_integrity import LibraryIntegrityService
from engine.library_maintenance import LibraryMaintenanceService
from engine.organizer import OrganizerService
from engine.pipeline import PipelineJob, QueueType
from engine.plugin_system import PluginService
from engine.recognition import RecognitionService
from engine.rename import RenameService
from engine.review import ReviewService
from engine.search_advanced import AdvancedSearchService
from engine.services import ImageService
from ui.background import BackgroundTaskManager


@dataclass(slots=True)
class LibraryBrowserPanel:
    library_service: LibraryService
    image_service: ImageService
    dropped_paths: list[str] = field(default_factory=list)
    last_summary: Any = None
    images: list[Any] = field(default_factory=list)

    def refresh(self) -> None:
        self.last_summary = self.library_service.summary()
        self.images = self.image_service.list_images()

    def handle_drop(self, paths: list[str | Path]) -> None:
        self.dropped_paths.extend(str(Path(item)) for item in paths)


@dataclass(slots=True)
class SearchPanel:
    service: AdvancedSearchService
    tasks: BackgroundTaskManager
    latest_results: list[Any] = field(default_factory=list)
    active_task_id: str | None = None

    def search_async(self, query_text: str) -> str:
        def _work(ctx):
            ctx.report_progress(10)
            job = PipelineJob(
                queue_type=QueueType.SEARCH,
                metadata={
                    "stage": "advanced_search",
                    "action": "search",
                    "query": {"query_text": query_text},
                },
            )
            result = self.service.process_advanced_search_job(job)
            ctx.report_progress(100)
            if result is None:
                return []
            response = result.payload.get("response")
            return [] if response is None else list(response.results)

        self.active_task_id = self.tasks.submit("search", _work)
        return self.active_task_id

    def sync_task(self) -> None:
        if self.active_task_id is None:
            return
        snapshot = self.tasks.snapshot(self.active_task_id)
        if snapshot is None or not snapshot.done:
            return
        if snapshot.result is not None:
            self.latest_results = list(snapshot.result)

    def cancel(self) -> bool:
        if self.active_task_id is None:
            return False
        return self.tasks.cancel(self.active_task_id)


@dataclass(slots=True)
class RecognitionPanel:
    service: RecognitionService
    tasks: BackgroundTaskManager
    progress: int = 0
    active_task_id: str | None = None

    def recognize_async(self, paths: list[str | Path]) -> str:
        normalized = [str(Path(item)) for item in paths]

        def _work(ctx):
            total = max(1, len(normalized))
            processed = 0
            for path in normalized:
                if ctx.is_cancelled():
                    break
                job = PipelineJob(source_path=path, queue_type=QueueType.RECOGNITION)
                self.service.process_recognition_job(job)
                processed += 1
                ctx.report_progress(int((processed / total) * 100))
            return processed

        self.active_task_id = self.tasks.submit("recognition", _work)
        return self.active_task_id

    def sync_task(self) -> None:
        if self.active_task_id is None:
            return
        snapshot = self.tasks.snapshot(self.active_task_id)
        if snapshot is None:
            return
        self.progress = snapshot.progress

    def cancel(self) -> bool:
        if self.active_task_id is None:
            return False
        return self.tasks.cancel(self.active_task_id)


@dataclass(slots=True)
class ReviewQueuePanel:
    service: ReviewService
    tick_interval: int = 1
    _ticks: int = 0
    items: list[Any] = field(default_factory=list)

    def refresh(self) -> None:
        self.items = list(self.service.filter_reviews())

    def tick(self) -> None:
        self._ticks += 1
        if self._ticks % max(1, self.tick_interval) == 0:
            self.refresh()


@dataclass(slots=True)
class CollectionManagerPanel:
    service: CollectionService
    hierarchy_cache: list[Any] = field(default_factory=list)

    def refresh(self) -> None:
        self.hierarchy_cache = self.service.hierarchy()


@dataclass(slots=True)
class DatasetManagerPanel:
    service: DatasetService
    tasks: BackgroundTaskManager
    progress: int = 0
    active_task_id: str | None = None

    def build_async(self, paths: list[str | Path]) -> str:
        normalized = [str(Path(item)) for item in paths]

        def _work(ctx):
            total = max(1, len(normalized))
            out = []
            for idx, path in enumerate(normalized, start=1):
                if ctx.is_cancelled():
                    break
                job = PipelineJob(
                    source_path=path,
                    queue_type=QueueType.SEARCH,
                    metadata={"stage": "dataset"},
                )
                result = self.service.process_dataset_job(job)
                if result is not None:
                    out.append(result)
                ctx.report_progress(int((idx / total) * 100))
            return out

        self.active_task_id = self.tasks.submit("dataset", _work)
        return self.active_task_id

    def sync_task(self) -> None:
        if self.active_task_id is None:
            return
        snapshot = self.tasks.snapshot(self.active_task_id)
        if snapshot is not None:
            self.progress = snapshot.progress


@dataclass(slots=True)
class BulkOperationsPanel:
    service: BulkService
    tasks: BackgroundTaskManager
    progress: int = 0
    active_task_id: str | None = None

    def run_async(self, operation: str, *, image_ids: list[int], destination: str | None = None) -> str:
        def _work(ctx):
            ctx.report_progress(10)
            if operation == "delete":
                result = self.service.delete_images(image_ids)
            elif operation == "move":
                result = self.service.move_images(image_ids, destination or ".")
            elif operation == "copy":
                result = self.service.copy_images(image_ids, destination or ".")
            else:
                result = self.service.rename_images(image_ids)
            ctx.report_progress(100)
            return result

        self.active_task_id = self.tasks.submit("bulk", _work)
        return self.active_task_id

    def sync_task(self) -> None:
        if self.active_task_id is None:
            return
        snapshot = self.tasks.snapshot(self.active_task_id)
        if snapshot is not None:
            self.progress = snapshot.progress

    def cancel(self) -> bool:
        if self.active_task_id is None:
            return False
        return self.tasks.cancel(self.active_task_id)


@dataclass(slots=True)
class RenamePanel:
    service: RenameService


@dataclass(slots=True)
class OrganizerPanel:
    service: OrganizerService


@dataclass(slots=True)
class LibraryIntegrityPanel:
    service: LibraryIntegrityService
    tasks: BackgroundTaskManager
    latest_report: Any = None
    active_scan_id: str | None = None

    def run_quick_scan_async(self) -> str:
        scan_id = f"integrity-{datetime.now(timezone.utc).isoformat()}"
        self.active_scan_id = scan_id

        def _work(ctx):
            ctx.report_progress(10)
            report = self.service.run_quick_scan(scan_id=scan_id)
            ctx.report_progress(100)
            return report

        return self.tasks.submit("integrity", _work)

    def cancel(self) -> None:
        if self.active_scan_id is not None:
            self.service.cancel_scan(self.active_scan_id)


@dataclass(slots=True)
class LibraryMaintenancePanel:
    service: LibraryMaintenanceService
    tasks: BackgroundTaskManager
    latest_report: Any = None
    active_job_id: str | None = None

    def run_preview_async(self) -> str:
        job_id = f"maintenance-{datetime.now(timezone.utc).isoformat()}"
        self.active_job_id = job_id

        def _work(ctx):
            ctx.report_progress(20)
            report = self.service.preview_repairs()
            ctx.report_progress(100)
            return report

        return self.tasks.submit("maintenance", _work)

    def cancel(self) -> None:
        if self.active_job_id is not None:
            self.service.cancel_job(self.active_job_id)


@dataclass(slots=True)
class KnowledgeBasePanel:
    service: KnowledgeBaseService
    statistics: dict[str, Any] = field(default_factory=dict)

    def refresh_statistics(self) -> None:
        job = PipelineJob(
            queue_type=QueueType.SEARCH,
            metadata={"stage": "knowledge_base", "action": "statistics"},
        )
        result = self.service.process_knowledge_base_job(job)
        if result is None:
            self.statistics = {}
            return
        snapshot = result.payload.get("statistics")
        if snapshot is None:
            self.statistics = {}
            return
        self.statistics = {
            "datasets": snapshot.datasets,
            "characters": snapshot.characters,
            "series": snapshot.series,
            "aliases": snapshot.aliases,
            "training_samples": snapshot.training_samples,
            "reference_images": snapshot.reference_images,
        }


@dataclass(slots=True)
class CharacterDatabasePanel:
    service: CharacterDatabaseService
    statistics: dict[str, Any] = field(default_factory=dict)

    def refresh_statistics(self) -> None:
        validation = self.service.validate_database(strict=False)
        self.statistics = {
            "valid": validation.valid,
            "issues": len(validation.issues),
            "characters": len(self.service.search_characters("")),
            "series": len(self.service.search_series("")),
        }


@dataclass(slots=True)
class AutomationManagerPanel:
    service: AutomationService
    state: dict[str, Any] = field(default_factory=dict)

    def refresh_state(self) -> None:
        progress_job = PipelineJob(queue_type=QueueType.SEARCH, metadata={"stage": "automation", "action": "progress"})
        history_job = PipelineJob(queue_type=QueueType.SEARCH, metadata={"stage": "automation", "action": "history"})
        progress = self.service.process_automation_job(progress_job)
        history = self.service.process_automation_job(history_job)
        self.state = {
            "progress": None if progress is None else progress.payload.get("progress"),
            "history": [] if history is None else history.payload.get("history", []),
        }


@dataclass(slots=True)
class PluginManagerPanel:
    service: PluginService
    health: dict[str, Any] = field(default_factory=dict)

    def refresh_health(self) -> None:
        job = PipelineJob(queue_type=QueueType.SEARCH, metadata={"stage": "plugin_system", "action": "health"})
        result = self.service.process_plugin_job(job)
        self.health = {} if result is None else dict(result.payload.get("health", {}))
