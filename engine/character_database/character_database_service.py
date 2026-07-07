from __future__ import annotations

from engine.character_database.character_database_engine import CharacterDatabaseEngine
from engine.character_database.character_database_models import CharacterRecord, DisambiguationEntry, SeriesRecord


class CharacterDatabaseService:
    """Service facade for canonical character knowledge operations."""

    def __init__(self, *, engine: CharacterDatabaseEngine | None = None) -> None:
        self.engine = engine or CharacterDatabaseEngine(callback=self._handle_event)

    def create_character(self, **kwargs) -> CharacterRecord:
        return self.engine.create_character(**kwargs)

    def create_series(self, **kwargs) -> SeriesRecord:
        return self.engine.create_series(**kwargs)

    def lookup_character(self, identifier: int | str) -> CharacterRecord | None:
        return self.engine.lookup_character(identifier)

    def lookup_series(self, identifier: int | str) -> SeriesRecord | None:
        return self.engine.lookup_series(identifier)

    def search_characters(self, query: str, *, fuzzy: bool = True) -> list[CharacterRecord]:
        return self.engine.search_characters(query, fuzzy=fuzzy)

    def search_series(self, query: str, *, fuzzy: bool = True) -> list[SeriesRecord]:
        return self.engine.search_series(query, fuzzy=fuzzy)

    def resolve_alias(self, alias: str) -> list[CharacterRecord]:
        return self.engine.resolve_alias(alias)

    def disambiguate(self, canonical_name: str) -> list[DisambiguationEntry]:
        return self.engine.disambiguate(canonical_name)

    def validate_database(self, *, strict: bool = False):
        return self.engine.validate_database(strict=strict)

    def import_characters(self, payloads: list[dict], *, job_id: str | None = None, resumed: bool = False) -> list[CharacterRecord]:
        return self.engine.import_characters(payloads, job_id=job_id, resumed=resumed)

    def import_series(self, payloads: list[dict], *, job_id: str | None = None, resumed: bool = False) -> list[SeriesRecord]:
        return self.engine.import_series(payloads, job_id=job_id, resumed=resumed)

    def merge_database(self, payload: dict, *, job_id: str | None = None, resumed: bool = False) -> dict:
        return self.engine.merge_database(payload, job_id=job_id, resumed=resumed)

    def merge_character(self, source_character_id: int, target_character_id: int) -> CharacterRecord:
        return self.engine.merge_character(source_character_id, target_character_id)

    def merge_series(self, source_series_id: int, target_series_id: int) -> SeriesRecord:
        return self.engine.merge_series(source_series_id, target_series_id)

    def request_cancel(self, job_id: str) -> None:
        self.engine.request_cancel(job_id)

    def _handle_event(self, event: object) -> None:
        return None
