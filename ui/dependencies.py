from __future__ import annotations

from dataclasses import dataclass

from engine.automation import AutomationService
from engine.bulk import BulkService
from engine.character_database import CharacterDatabaseService
from engine.collections import CollectionService
from engine.config import settings
from engine.dataset import DatasetService
from engine.knowledge_base import KnowledgeBaseService
from engine.library import LibraryService
from engine.library_integrity import LibraryIntegrityService
from engine.library_maintenance import LibraryMaintenanceService
from engine.metadata import MetadataService
from engine.organizer import OrganizerService
from engine.pipeline import QueueManager
from engine.plugin_system import PluginService
from engine.recognition import RecognitionService
from engine.rename import RenameService
from engine.review import ReviewService
from engine.search_advanced import AdvancedSearchService
from engine.services import ImageService, JobService
from engine.thumbnails import ThumbnailService


@dataclass(slots=True)
class ServiceContainer:
    queue_manager: QueueManager
    library_service: LibraryService
    search_service: AdvancedSearchService
    recognition_service: RecognitionService
    review_service: ReviewService
    collection_service: CollectionService
    dataset_service: DatasetService
    bulk_service: BulkService
    rename_service: RenameService
    organizer_service: OrganizerService
    integrity_service: LibraryIntegrityService
    maintenance_service: LibraryMaintenanceService
    knowledge_base_service: KnowledgeBaseService
    character_database_service: CharacterDatabaseService
    automation_service: AutomationService
    plugin_service: PluginService
    image_service: ImageService
    metadata_service: MetadataService
    thumbnail_service: ThumbnailService
    job_service: JobService


class DependencyContainer:
    def __init__(self) -> None:
        self._services: ServiceContainer | None = None

    def services(self) -> ServiceContainer:
        if self._services is None:
            queue_manager = QueueManager()
            self._services = ServiceContainer(
                queue_manager=queue_manager,
                library_service=LibraryService(),
                search_service=AdvancedSearchService(queue_manager=queue_manager),
                recognition_service=RecognitionService(queue_manager=queue_manager),
                review_service=ReviewService(queue_manager=queue_manager),
                collection_service=CollectionService(queue_manager=queue_manager),
                dataset_service=DatasetService(queue_manager=queue_manager),
                bulk_service=BulkService(),
                rename_service=RenameService(queue_manager=queue_manager),
                organizer_service=OrganizerService(queue_manager=queue_manager),
                integrity_service=LibraryIntegrityService(),
                maintenance_service=LibraryMaintenanceService(),
                knowledge_base_service=KnowledgeBaseService(queue_manager=queue_manager),
                character_database_service=CharacterDatabaseService(),
                automation_service=AutomationService(queue_manager=queue_manager),
                plugin_service=PluginService(queue_manager=queue_manager),
                image_service=ImageService(),
                metadata_service=MetadataService(queue_manager=queue_manager),
                thumbnail_service=ThumbnailService(queue_manager=queue_manager),
                job_service=JobService(),
            )
        return self._services

    @property
    def workspace(self):
        return settings.workspace
