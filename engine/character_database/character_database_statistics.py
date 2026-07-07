from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CharacterDatabaseStatistics:
    characters: int = 0
    series: int = 0
    aliases: int = 0
    relationships: int = 0
    imports: int = 0
    validation_runs: int = 0
    duplicates: int = 0
    lookup_count: int = 0
    total_lookup_time_seconds: float = 0.0

    @property
    def average_lookup_time_seconds(self) -> float:
        if self.lookup_count <= 0:
            return 0.0
        return round(self.total_lookup_time_seconds / float(self.lookup_count), 8)

    def record_lookup(self, elapsed_seconds: float) -> None:
        self.lookup_count += 1
        self.total_lookup_time_seconds += max(0.0, elapsed_seconds)

    def record_validation(self, duplicate_count: int) -> None:
        self.validation_runs += 1
        self.duplicates += max(0, duplicate_count)

    def record_import(self, imported_records: int) -> None:
        if imported_records > 0:
            self.imports += imported_records

    def sync_counts(self, *, characters: int, series: int, aliases: int, relationships: int) -> None:
        self.characters = max(0, characters)
        self.series = max(0, series)
        self.aliases = max(0, aliases)
        self.relationships = max(0, relationships)
