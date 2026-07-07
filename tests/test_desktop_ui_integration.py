from __future__ import annotations

from pathlib import Path
import time

import pytest

from engine.config import settings
from engine.database.database import database_manager
from engine.pipeline import PipelineJob, QueueType
from ui.application import DesktopApplication
from ui.preferences import PreferencesStore


@pytest.fixture()
def ui_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    return tmp_path


def test_window_creation_and_widget_initialization(ui_env: Path) -> None:
    app = DesktopApplication.create()

    assert app.window is not None
    assert app.window.sidebar.active == "library"
    assert app.window.status_bar.message == "Ready"
    assert app.window.thumbnail_grid.thumbnails == []
    assert app.window.logging_console.lines == []

    app.shutdown()


def test_navigation_and_toolbar_shortcuts(ui_env: Path) -> None:
    app = DesktopApplication.create()

    app.window.navigate("search")
    assert app.window.active_panel_id == "search"
    assert app.window.apply_shortcut("search") == "Ctrl+F"

    app.shutdown()


def test_service_wiring_for_panels(ui_env: Path) -> None:
    app = DesktopApplication.create()
    services = app.dependencies.services()

    assert app.window.panels["library"].library_service is services.library_service
    assert app.window.panels["search"].service is services.search_service
    assert app.window.panels["recognition"].service is services.recognition_service
    assert app.window.panels["plugins"].service is services.plugin_service
    assert app.window.panels["automation"].service is services.automation_service

    app.shutdown()


def test_background_jobs_progress_and_search_async(ui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = DesktopApplication.create()
    panel = app.window.panels["search"]

    def _fake_process(job):
        class _Resp:
            results = ["r1", "r2"]

        class _Result:
            payload = {"response": _Resp()}

        return _Result()

    monkeypatch.setattr(panel.service, "process_advanced_search_job", _fake_process)

    panel.search_async("heroine")
    for _ in range(50):
        app.tick()
        if panel.latest_results:
            break

    assert panel.latest_results == ["r1", "r2"]
    app.shutdown()


def test_cancellation_for_bulk_operation(ui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = DesktopApplication.create()
    panel = app.window.panels["bulk"]

    def _slow_delete(image_ids):
        return {"deleted": len(image_ids)}

    monkeypatch.setattr(panel.service, "delete_images", _slow_delete)

    panel.run_async("delete", image_ids=[1, 2, 3])
    assert panel.cancel() is True

    app.shutdown()


def test_settings_persistence_and_theme_switching(ui_env: Path) -> None:
    app = DesktopApplication.create()
    app.window.switch_theme("dark")
    app.window.settings_window.set_shortcut("search", "Ctrl+Shift+F")
    app.preferences.last_active_panel = "plugins"
    app.shutdown()

    reloaded = DesktopApplication.create()
    assert reloaded.preferences.theme == "dark"
    assert reloaded.preferences.custom_shortcuts["search"] == "Ctrl+Shift+F"
    assert reloaded.preferences.last_active_panel == "plugins"
    reloaded.shutdown()


def test_drag_drop_and_image_preview(ui_env: Path) -> None:
    app = DesktopApplication.create()
    image_path = ui_env / "sample.png"
    image_path.write_bytes(b"x")

    app.window.handle_drag_drop([image_path])
    app.window.update_preview(
        image_path=image_path,
        metadata={"mime": "image/png", "width": 512},
        thumbnails=[image_path],
    )

    library_panel = app.window.panels["library"]
    assert str(image_path) in library_panel.dropped_paths
    assert app.window.image_preview.current_path == image_path
    assert app.window.metadata_inspector.metadata["mime"] == "image/png"
    assert app.window.thumbnail_grid.thumbnails == [image_path]
    app.shutdown()


def test_review_queue_auto_refresh(ui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = DesktopApplication.create()
    panel = app.window.panels["review"]

    monkeypatch.setattr(panel.service, "filter_reviews", lambda: ["review-1"])  # deterministic refresh
    app.tick()

    assert panel.items == ["review-1"]
    app.shutdown()


def test_job_monitor_updates(ui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = DesktopApplication.create()
    services = app.dependencies.services()

    monkeypatch.setattr(
        services.queue_manager,
        "statistics",
        lambda: {QueueType.SEARCH: {"queued": 2, "dequeued": 1, "completed": 0, "failed": 0, "cancelled": 0}},
    )
    monkeypatch.setattr(services.job_service, "list_running_jobs", lambda: ["job-a"])

    app.tick()

    assert app.window.job_monitor.queue_stats["search"]["queued"] == 2
    assert app.window.job_monitor.running_jobs == ["job-a"]
    app.shutdown()


def test_notifications_and_graceful_shutdown(ui_env: Path) -> None:
    app = DesktopApplication.create()
    app.start()
    app.notifications.notify("Info", "Panel loaded")

    notes = app.notifications.list_notifications()
    assert len(notes) >= 2

    app.shutdown()
    prefs_path = PreferencesStore(settings.workspace).path
    assert prefs_path.exists()


def test_plugin_health_and_automation_state_panels(ui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = DesktopApplication.create()

    plugin_panel = app.window.panels["plugins"]
    automation_panel = app.window.panels["automation"]

    def _plugin_result(_job):
        class _Result:
            payload = {"health": {"plug": {"status": "ok"}}}

        return _Result()

    def _automation_result(job):
        action = (job.metadata or {}).get("action")

        class _Result:
            payload = {"progress": "p", "history": ["h"]}

        if action == "progress":
            return _Result()
        if action == "history":
            return _Result()
        return None

    monkeypatch.setattr(plugin_panel.service, "process_plugin_job", _plugin_result)
    monkeypatch.setattr(automation_panel.service, "process_automation_job", _automation_result)

    plugin_panel.refresh_health()
    automation_panel.refresh_state()

    assert plugin_panel.health["plug"]["status"] == "ok"
    assert automation_panel.state["progress"] == "p"
    assert automation_panel.state["history"] == ["h"]

    app.shutdown()


def test_knowledge_base_character_integrity_maintenance_panels(ui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = DesktopApplication.create()

    kb_panel = app.window.panels["knowledge_base"]
    char_panel = app.window.panels["character_database"]
    integrity_panel = app.window.panels["integrity"]
    maintenance_panel = app.window.panels["maintenance"]

    class _Stats:
        datasets = 1
        characters = 2
        series = 3
        aliases = 4
        training_samples = 5
        reference_images = 6

    class _KbResult:
        payload = {"statistics": _Stats()}

    monkeypatch.setattr(kb_panel.service, "process_knowledge_base_job", lambda _job: _KbResult())

    class _Validation:
        valid = True
        issues = []

    monkeypatch.setattr(char_panel.service, "validate_database", lambda strict=False: _Validation())
    monkeypatch.setattr(char_panel.service, "search_characters", lambda _q: [1, 2, 3])
    monkeypatch.setattr(char_panel.service, "search_series", lambda _q: [1, 2])

    kb_panel.refresh_statistics()
    char_panel.refresh_statistics()

    assert kb_panel.statistics["datasets"] == 1
    assert char_panel.statistics["characters"] == 3
    assert char_panel.statistics["series"] == 2

    monkeypatch.setattr(integrity_panel.service, "run_quick_scan", lambda scan_id=None: {"mode": "quick", "scan_id": scan_id})
    monkeypatch.setattr(maintenance_panel.service, "preview_repairs", lambda: {"preview": True})

    integrity_task = integrity_panel.run_quick_scan_async()
    maintenance_task = maintenance_panel.run_preview_async()

    for _ in range(200):
        if app.tasks.snapshot(integrity_task).done and app.tasks.snapshot(maintenance_task).done:
            break
        time.sleep(0.005)

    assert app.tasks.snapshot(integrity_task).result["mode"] == "quick"
    assert app.tasks.snapshot(maintenance_task).result["preview"] is True

    app.shutdown()
