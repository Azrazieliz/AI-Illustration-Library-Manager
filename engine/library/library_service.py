from __future__ import annotations

from engine.library.library_engine import LibraryEngine
from engine.library.library_models import (
    LibraryAnalysisReport,
    LibraryHealthReport,
    LibraryStatisticsReport,
    LibrarySummary,
)


class LibraryService:
    """Service facade for library-wide analysis and management insights."""

    def __init__(self, *, engine: LibraryEngine | None = None) -> None:
        self.engine = engine or LibraryEngine()

    def summary(self) -> LibrarySummary:
        return self.engine.summary()

    def statistics(self) -> LibraryStatisticsReport:
        return self.engine.statistics()

    def health(self) -> LibraryHealthReport:
        return self.engine.health()

    def analyze(self) -> LibraryAnalysisReport:
        return self.engine.analyze()
