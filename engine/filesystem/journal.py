from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.config import settings


class TransactionJournal:
    """Persist transaction metadata as JSON files for review and recovery."""

    def __init__(self, log_directory: Path | None = None) -> None:
        self._log_directory = Path(log_directory or settings.log_directory) / "transactions"
        self._log_directory.mkdir(parents=True, exist_ok=True)

    def write(self, payload: dict[str, Any]) -> Path:
        """Write a transaction payload to disk as a JSON file."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        path = self._log_directory / f"{timestamp}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path
