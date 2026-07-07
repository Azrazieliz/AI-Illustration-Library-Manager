from __future__ import annotations

from engine.library_integrity.integrity_engine import LibraryIntegrityEngine
from engine.library_integrity.integrity_models import IntegrityCheckpoint, IntegrityReport


class LibraryIntegrityService:
    """Service facade for library integrity scan modes."""

    def __init__(self, *, engine: LibraryIntegrityEngine | None = None) -> None:
        self.engine = engine or LibraryIntegrityEngine(callback=self._handle_event)

    def run_full_scan(self, *, scan_id: str | None = None, checkpoint: IntegrityCheckpoint | None = None, resumed: bool = False) -> IntegrityReport:
        return self.engine.run_full_scan(scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)

    def run_quick_scan(self, *, scan_id: str | None = None, checkpoint: IntegrityCheckpoint | None = None, resumed: bool = False) -> IntegrityReport:
        return self.engine.run_quick_scan(scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)

    def run_database_scan(self, *, scan_id: str | None = None, checkpoint: IntegrityCheckpoint | None = None, resumed: bool = False) -> IntegrityReport:
        return self.engine.run_database_scan(scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)

    def run_filesystem_scan(self, *, scan_id: str | None = None, checkpoint: IntegrityCheckpoint | None = None, resumed: bool = False) -> IntegrityReport:
        return self.engine.run_filesystem_scan(scan_id=scan_id, checkpoint=checkpoint, resumed=resumed)

    def cancel_scan(self, scan_id: str) -> None:
        self.engine.request_cancel(scan_id)

    def checkpoint_for(self, scan_id: str) -> IntegrityCheckpoint:
        return self.engine.checkpoint_for(scan_id)

    def _handle_event(self, event: object) -> None:
        return None
