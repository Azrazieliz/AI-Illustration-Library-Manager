from __future__ import annotations

from dataclasses import fields
from dataclasses import dataclass
from threading import Event, Thread
from time import sleep
from typing import Any, Callable

from engine.automation import AutomationService
from engine.collections import CollectionService
from engine.config import settings
from engine.database import DatabaseManager, UnitOfWork, get_database_manager, remove_scoped_session
from engine.duplicates import DuplicateService
from engine.embeddings import EmbeddingService
from engine.export import ExportService
from engine.hashing import HashService
from engine.indexer import IndexerService, IncrementalIndexer
from engine.knowledge_base import KnowledgeBaseService
from engine.library import LibraryService
from engine.knowledge_graph import KnowledgeGraphService
from engine.logging import get_logger
from engine.metadata import MetadataService
from engine.pipeline import PipelineJob, QueueManager, QueueType
from engine.plugin_system import PluginService
from engine.recognition import RecognitionService
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.hash_repository import HashRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.thumbnail_repository import ThumbnailRepository
from engine.review import ReviewService
from engine.scanner import ScannerManager
from engine.search import SearchService
from engine.search_advanced import AdvancedSearchService
from engine.tagging import TaggingService
from engine.thumbnails import ThumbnailService
from engine.dataset import DatasetService


QueueHandler = Callable[[PipelineJob], Any]


class RuntimeQueueWorker:
    """Own one queue and invoke its composition-root supplied handler."""

    def __init__(self, queue_manager: QueueManager, queue_type: QueueType, handler: QueueHandler) -> None:
        self.queue_manager = queue_manager
        self.queue_type = queue_type
        self.handler = handler
        self._stop_event = Event()
        self._thread: Thread | None = None

    @property
    def name(self) -> str:
        return f"runtime-{self.queue_type.value}-worker"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name=self.name)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                job = self.queue_manager.dequeue(self.queue_type)
                if job is None:
                    sleep(0.05)
                    continue
                try:
                    self.handler(job)
                except Exception as exc:  # pragma: no cover - defensive runtime boundary
                    self.queue_manager.mark_failed(self.queue_type, job, str(exc))
                    get_logger(self.name).exception("Pipeline job failed")
                else:
                    self.queue_manager.mark_completed(self.queue_type, job)
        finally:
            remove_scoped_session()


class AutomationScheduler:
    """Lifecycle owner for the existing automation engine's due-job checks."""

    def __init__(self, service: AutomationService, *, interval_seconds: float = 1.0) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True, name="automation-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        try:
            while not self._stop_event.wait(self.interval_seconds):
                try:
                    self.service.engine.run_due()
                except Exception:  # pragma: no cover - defensive runtime boundary
                    get_logger("automation-scheduler").exception("Automation scheduler iteration failed")
        finally:
            remove_scoped_session()


@dataclass(slots=True)
class RuntimeRepositories:
    image: ImageRepository
    hash: HashRepository
    duplicate: DuplicateRepository
    thumbnail: ThumbnailRepository
    metadata: MetadataRepository
    embedding: EmbeddingRepository


@dataclass(slots=True)
class RuntimeServices:
    scanner: ScannerManager
    indexer: IndexerService
    hash: HashService
    duplicate: DuplicateService
    thumbnail: ThumbnailService
    metadata: MetadataService
    embedding: EmbeddingService
    recognition: RecognitionService
    review: ReviewService
    search: SearchService
    advanced_search: AdvancedSearchService
    knowledge_graph: KnowledgeGraphService
    tagging: TaggingService
    dataset: DatasetService
    export: ExportService
    collections: CollectionService
    library: LibraryService
    automation: AutomationService
    plugins: PluginService
    knowledge_base: KnowledgeBaseService


class ApplicationHost:
    """Composition root for the existing repository, service, and worker layers."""

    def __init__(self) -> None:
        self.configuration = settings
        self.database: DatabaseManager = get_database_manager()
        self.unit_of_work = UnitOfWork()
        self.queue_manager = QueueManager()
        self.repositories = RuntimeRepositories(
            image=ImageRepository(),
            hash=HashRepository(),
            duplicate=DuplicateRepository(),
            thumbnail=ThumbnailRepository(),
            metadata=MetadataRepository(),
            embedding=EmbeddingRepository(),
        )
        self.services = self._build_services()
        self.scheduler = AutomationScheduler(self.services.automation)
        self.workers = self._build_workers()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.database.initialize()
        for worker in self.workers.values():
            worker.start()
        self.scheduler.start()
        self._started = True
        get_logger("runtime").info("Application host started", extra={"queue_consumers": len(self.workers)})

    def shutdown(self) -> None:
        if not self._started:
            return
        self.scheduler.stop()
        self.services.scanner.service.cancel_scan()
        for worker in reversed(list(self.workers.values())):
            worker.stop()
        for repo_field in fields(self.repositories):
            repository = getattr(self.repositories, repo_field.name)
            repository.close()
        remove_scoped_session()
        self._started = False
        get_logger("runtime").info("Application host stopped")

    def run_forever(self) -> None:
        self.start()
        try:
            while True:
                sleep(0.25)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def _build_services(self) -> RuntimeServices:
        from engine.duplicates.duplicate_engine import DuplicateEngine
        from engine.hashing.hash_engine import HashEngine
        from engine.metadata.metadata_engine import MetadataEngine
        from engine.thumbnails.thumbnail_engine import ThumbnailEngine

        scanner = ScannerManager(queue_manager=self.queue_manager)
        indexer = IndexerService(
            queue_manager=self.queue_manager,
            indexer=IncrementalIndexer(repository=self.repositories.image),
        )
        hash_service = HashService(
            queue_manager=self.queue_manager,
            hash_engine=HashEngine(
                image_repository=self.repositories.image,
                hash_repository=self.repositories.hash,
            ),
        )
        duplicate = DuplicateService(
            queue_manager=self.queue_manager,
            engine=DuplicateEngine(
                image_repository=self.repositories.image,
                hash_repository=self.repositories.hash,
                duplicate_repository=self.repositories.duplicate,
            ),
        )
        thumbnail = ThumbnailService(
            queue_manager=self.queue_manager,
            engine=ThumbnailEngine(
                image_repository=self.repositories.image,
                thumbnail_repository=self.repositories.thumbnail,
            ),
        )
        metadata = MetadataService(
            queue_manager=self.queue_manager,
            engine=MetadataEngine(
                image_repository=self.repositories.image,
                metadata_repository=self.repositories.metadata,
            ),
        )
        return RuntimeServices(
            scanner=scanner,
            indexer=indexer,
            hash=hash_service,
            duplicate=duplicate,
            thumbnail=thumbnail,
            metadata=metadata,
            embedding=EmbeddingService(queue_manager=self.queue_manager),
            recognition=RecognitionService(queue_manager=self.queue_manager),
            review=ReviewService(queue_manager=self.queue_manager),
            search=SearchService(queue_manager=self.queue_manager),
            advanced_search=AdvancedSearchService(queue_manager=self.queue_manager),
            knowledge_graph=KnowledgeGraphService(queue_manager=self.queue_manager),
            tagging=TaggingService(queue_manager=self.queue_manager),
            dataset=DatasetService(queue_manager=self.queue_manager),
            export=ExportService(queue_manager=self.queue_manager),
            collections=CollectionService(queue_manager=self.queue_manager),
            library=LibraryService(),
            automation=AutomationService(queue_manager=self.queue_manager),
            plugins=PluginService(queue_manager=self.queue_manager),
            knowledge_base=KnowledgeBaseService(queue_manager=self.queue_manager),
        )

    def _build_workers(self) -> dict[QueueType, RuntimeQueueWorker]:
        return {
            QueueType.DISCOVERY: RuntimeQueueWorker(self.queue_manager, QueueType.DISCOVERY, self.services.indexer.process_discovery_job),
            QueueType.INDEX: RuntimeQueueWorker(self.queue_manager, QueueType.INDEX, self.services.indexer.process_discovery_job),
            QueueType.HASH: RuntimeQueueWorker(self.queue_manager, QueueType.HASH, self.services.hash.process_hash_job),
            QueueType.DUPLICATE: RuntimeQueueWorker(self.queue_manager, QueueType.DUPLICATE, self.services.duplicate.process_duplicate_job),
            QueueType.THUMBNAIL: RuntimeQueueWorker(self.queue_manager, QueueType.THUMBNAIL, self.services.thumbnail.process_review_job),
            QueueType.METADATA: RuntimeQueueWorker(self.queue_manager, QueueType.METADATA, self.services.metadata.process_metadata_job),
            QueueType.EMBEDDING: RuntimeQueueWorker(self.queue_manager, QueueType.EMBEDDING, self.services.embedding.process_embedding_job),
            QueueType.RECOGNITION: RuntimeQueueWorker(self.queue_manager, QueueType.RECOGNITION, self.services.recognition.process_recognition_job),
            QueueType.REVIEW: RuntimeQueueWorker(self.queue_manager, QueueType.REVIEW, self.services.review.process_review_job),
            QueueType.SEARCH: RuntimeQueueWorker(self.queue_manager, QueueType.SEARCH, self._route_search_job),
            QueueType.TRANSACTION: RuntimeQueueWorker(self.queue_manager, QueueType.TRANSACTION, self._route_transaction_job),
        }

    def _route_search_job(self, job: PipelineJob) -> Any:
        stage = str((job.metadata or {}).get("stage", "search"))
        handlers: dict[str, QueueHandler] = {
            "search": self.services.search.process_search_job,
            "advanced_search": self.services.advanced_search.process_advanced_search_job,
            "knowledge_graph": self.services.knowledge_graph.process_knowledge_graph_job,
            "tagging": self.services.tagging.process_tagging_job,
            "dataset": self.services.dataset.process_dataset_job,
            "export": self.services.export.process_export_job,
            "collection": self.services.collections.process_collection_job,
            "automation": self.services.automation.process_automation_job,
            "plugin_system": self.services.plugins.process_plugin_job,
            "knowledge_base": self.services.knowledge_base.process_knowledge_base_job,
        }
        handler = handlers.get(stage)
        if handler is None:
            raise ValueError(f"No SEARCH consumer registered for stage '{stage}'")
        return handler(job)

    @staticmethod
    def _route_transaction_job(job: PipelineJob) -> None:
        raise ValueError("No transaction pipeline operation is registered for this job")
