from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class UIPreferences:
    theme: str = "light"
    sidebar_collapsed: bool = False
    last_active_panel: str = "library"
    window_width: int = 1280
    window_height: int = 800
    keyboard_shortcuts_enabled: bool = True
    custom_shortcuts: dict[str, str] = field(default_factory=dict)


class PreferencesStore:
    def __init__(self, root: Path) -> None:
        self._path = root / ".ui" / "preferences.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> UIPreferences:
        if not self._path.exists():
            return UIPreferences()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return UIPreferences(**payload)

    def save(self, prefs: UIPreferences) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(prefs), indent=2, sort_keys=True), encoding="utf-8")
