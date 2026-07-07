from __future__ import annotations

from dataclasses import dataclass

from engine.config import bootstrap_directories
from ui.background import BackgroundTaskManager
from ui.dependencies import DependencyContainer
from ui.main_window import DesktopMainWindow
from ui.notifications import NotificationCenter
from ui.panels import (
    AutomationManagerPanel,
    BulkOperationsPanel,
    CharacterDatabasePanel,
    CollectionManagerPanel,
    DatasetManagerPanel,
    KnowledgeBasePanel,
    LibraryBrowserPanel,
    LibraryIntegrityPanel,
    LibraryMaintenancePanel,
    OrganizerPanel,
    PluginManagerPanel,
    RecognitionPanel,
    RenamePanel,
    ReviewQueuePanel,
    SearchPanel,
)
from ui.preferences import PreferencesStore, UIPreferences


@dataclass(slots=True)
class DesktopApplication:
    dependencies: DependencyContainer
    preferences_store: PreferencesStore
    preferences: UIPreferences
    notifications: NotificationCenter
    tasks: BackgroundTaskManager
    window: DesktopMainWindow

    @classmethod
    def create(cls) -> "DesktopApplication":
        bootstrap_directories()
        dependencies = DependencyContainer()
        preferences_store = PreferencesStore(dependencies.workspace)
        preferences = preferences_store.load()
        notifications = NotificationCenter()
        tasks = BackgroundTaskManager(max_workers=4)

        services = dependencies.services()
        panels = {
            "library": LibraryBrowserPanel(services.library_service, services.image_service),
            "search": SearchPanel(services.search_service, tasks),
            "recognition": RecognitionPanel(services.recognition_service, tasks),
            "review": ReviewQueuePanel(services.review_service),
            "collections": CollectionManagerPanel(services.collection_service),
            "dataset": DatasetManagerPanel(services.dataset_service, tasks),
            "bulk": BulkOperationsPanel(services.bulk_service, tasks),
            "rename": RenamePanel(services.rename_service),
            "organizer": OrganizerPanel(services.organizer_service),
            "integrity": LibraryIntegrityPanel(services.integrity_service, tasks),
            "maintenance": LibraryMaintenancePanel(services.maintenance_service, tasks),
            "knowledge_base": KnowledgeBasePanel(services.knowledge_base_service),
            "character_database": CharacterDatabasePanel(services.character_database_service),
            "automation": AutomationManagerPanel(services.automation_service),
            "plugins": PluginManagerPanel(services.plugin_service),
        }
        window = DesktopMainWindow(preferences=preferences, panels=panels)

        return cls(
            dependencies=dependencies,
            preferences_store=preferences_store,
            preferences=preferences,
            notifications=notifications,
            tasks=tasks,
            window=window,
        )

    def start(self) -> None:
        self.notifications.notify("Desktop UI", "Application started")
        self.window.log("Desktop application started")

    def tick(self) -> None:
        panels = self.window.panels
        if "review" in panels:
            panels["review"].tick()
        if "search" in panels:
            panels["search"].sync_task()
        if "recognition" in panels:
            panels["recognition"].sync_task()
        if "dataset" in panels:
            panels["dataset"].sync_task()
        if "bulk" in panels:
            panels["bulk"].sync_task()

        services = self.dependencies.services()
        queue_stats = {
            queue_type.value: stats
            for queue_type, stats in services.queue_manager.statistics().items()
        }
        running_jobs = services.job_service.list_running_jobs()
        self.window.job_monitor.update(queue_stats=queue_stats, running_jobs=running_jobs)

    def shutdown(self) -> None:
        self.preferences_store.save(self.preferences)
        self.tasks.shutdown()
        self.notifications.notify("Desktop UI", "Application shutdown")
        self.window.log("Desktop application stopped")
