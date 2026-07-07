from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ui.preferences import UIPreferences
from ui.widgets import (
    ImagePreview,
    JobMonitor,
    LoggingConsole,
    MetadataInspector,
    NavigationSidebar,
    ProgressDialog,
    StatusBar,
    ThumbnailGrid,
    Toolbar,
)


@dataclass(slots=True)
class SettingsWindow:
    preferences: UIPreferences

    def set_theme(self, theme: str) -> None:
        self.preferences.theme = theme

    def set_shortcut(self, action: str, key_combo: str) -> None:
        self.preferences.custom_shortcuts[action] = key_combo


@dataclass(slots=True)
class DesktopMainWindow:
    preferences: UIPreferences
    panels: dict[str, Any]
    sidebar: NavigationSidebar = field(init=False)
    toolbar: Toolbar = field(init=False)
    status_bar: StatusBar = field(init=False)
    settings_window: SettingsWindow = field(init=False)
    job_monitor: JobMonitor = field(default_factory=JobMonitor)
    thumbnail_grid: ThumbnailGrid = field(default_factory=ThumbnailGrid)
    image_preview: ImagePreview = field(default_factory=ImagePreview)
    metadata_inspector: MetadataInspector = field(default_factory=MetadataInspector)
    logging_console: LoggingConsole = field(default_factory=LoggingConsole)
    progress_dialogs: dict[str, ProgressDialog] = field(default_factory=dict)

    def __post_init__(self) -> None:
        panel_ids = list(self.panels.keys())
        self.sidebar = NavigationSidebar(items=panel_ids, active=self.preferences.last_active_panel if self.preferences.last_active_panel in panel_ids else panel_ids[0])
        self.toolbar = Toolbar(
            actions={
                "refresh": "F5",
                "search": "Ctrl+F",
                "settings": "Ctrl+,",
                "cancel": "Esc",
            }
        )
        self.status_bar = StatusBar()
        self.settings_window = SettingsWindow(self.preferences)

    @property
    def active_panel_id(self) -> str:
        return self.sidebar.active

    def navigate(self, panel_id: str) -> None:
        self.sidebar.select(panel_id)
        self.preferences.last_active_panel = self.sidebar.active
        self.status_bar.set_status(f"Panel: {self.sidebar.active}")

    def switch_theme(self, theme: str) -> None:
        self.preferences.theme = theme
        self.status_bar.set_status(f"Theme switched to {theme}")

    def apply_shortcut(self, action: str) -> str | None:
        shortcuts = {**self.toolbar.actions, **self.preferences.custom_shortcuts}
        return shortcuts.get(action)

    def open_progress_dialog(self, key: str, title: str) -> ProgressDialog:
        dialog = ProgressDialog(title=title)
        self.progress_dialogs[key] = dialog
        return dialog

    def close_progress_dialog(self, key: str) -> None:
        self.progress_dialogs.pop(key, None)

    def handle_drag_drop(self, paths: list[str | Path]) -> None:
        library_panel = self.panels.get("library")
        if library_panel is not None:
            library_panel.handle_drop(paths)
        self.status_bar.set_status(f"Dropped {len(paths)} item(s)")

    def update_preview(self, image_path: str | Path, metadata: dict[str, Any], thumbnails: list[str | Path]) -> None:
        self.image_preview.show(image_path)
        self.metadata_inspector.inspect(metadata)
        self.thumbnail_grid.set_items([Path(item) for item in thumbnails])

    def log(self, message: str) -> None:
        self.logging_console.append(message)
