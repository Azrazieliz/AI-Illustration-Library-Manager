from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from engine.character_database.character_database_builder import CharacterDatabaseBuilder
from engine.character_database.character_database_exceptions import CharacterDatabaseValidationError, CharacterNotFoundError, SeriesNotFoundError
from engine.character_database.character_database_models import (
    AliasRecord,
    CharacterRecord,
    DisambiguationEntry,
    SeriesRecord,
    WorkerCheckpoint,
    WorkerProgress,
    WorkerTaskType,
)
from engine.character_database.character_database_statistics import CharacterDatabaseStatistics
from engine.repositories.character_database_repository import CharacterDatabaseRepository


class CharacterDatabaseEngine:
    """Canonical identity engine for character and series knowledge."""

    def __init__(
        self,
        *,
        repository: CharacterDatabaseRepository | None = None,
        builder: CharacterDatabaseBuilder | None = None,
        callback=None,
    ) -> None:
        self.repository = repository or CharacterDatabaseRepository()
        self.builder = builder or CharacterDatabaseBuilder()
        self.callback = callback
        self.statistics = CharacterDatabaseStatistics()
        self._cancel_requested: set[str] = set()
        self._checkpoints: dict[str, WorkerCheckpoint] = {}

    def create_character(self, **kwargs) -> CharacterRecord:
        record = self.repository.create_character(**kwargs)
        self._sync_statistics()
        return record

    def create_series(self, **kwargs) -> SeriesRecord:
        record = self.repository.create_series(**kwargs)
        self._sync_statistics()
        return record

    def find_character(self, character_id: int) -> CharacterRecord | None:
        return self.repository.find_character(character_id)

    def find_series(self, series_id: int) -> SeriesRecord | None:
        return self.repository.find_series(series_id)

    def lookup_character(self, identifier: int | str) -> CharacterRecord | None:
        started = perf_counter()
        result: CharacterRecord | None
        if isinstance(identifier, int):
            result = self.repository.find_character(identifier)
        elif identifier.strip().isdigit():
            result = self.repository.find_character(int(identifier.strip()))
        else:
            hits = self.repository.search_characters(identifier, fuzzy=True)
            result = hits[0] if hits else None
        self.statistics.record_lookup(perf_counter() - started)
        return result

    def lookup_series(self, identifier: int | str) -> SeriesRecord | None:
        started = perf_counter()
        result: SeriesRecord | None
        if isinstance(identifier, int):
            result = self.repository.find_series(identifier)
        elif identifier.strip().isdigit():
            result = self.repository.find_series(int(identifier.strip()))
        else:
            hits = self.repository.search_series(identifier, fuzzy=True)
            result = hits[0] if hits else None
        self.statistics.record_lookup(perf_counter() - started)
        return result

    def search_characters(self, query: str, *, fuzzy: bool = True) -> list[CharacterRecord]:
        started = perf_counter()
        result = self.repository.search_characters(query, fuzzy=fuzzy)
        self.statistics.record_lookup(perf_counter() - started)
        return result

    def search_series(self, query: str, *, fuzzy: bool = True) -> list[SeriesRecord]:
        started = perf_counter()
        result = self.repository.search_series(query, fuzzy=fuzzy)
        self.statistics.record_lookup(perf_counter() - started)
        return result

    def resolve_alias(self, alias: str) -> list[CharacterRecord]:
        started = perf_counter()
        result = self.repository.find_alias(alias)
        self.statistics.record_lookup(perf_counter() - started)
        return result

    def disambiguate(self, canonical_name: str) -> list[DisambiguationEntry]:
        started = perf_counter()
        query = canonical_name.strip().casefold()
        rows = [item for item in self.repository.list_characters() if item.canonical_name.strip().casefold() == query]
        rows.sort(key=lambda item: item.character_id)
        result = []
        for row in rows:
            series = self.repository.find_series(row.series_id) if row.series_id is not None else None
            result.append(self.builder.build_disambiguation_entry(character=row, series_title=series.canonical_title if series is not None else None))
        self.statistics.record_lookup(perf_counter() - started)
        return result

    def characters_for_series(self, series_id: int) -> list[CharacterRecord]:
        return self.repository.find_characters_by_series(series_id)

    def series_for_character(self, character_id: int) -> SeriesRecord | None:
        return self.repository.find_series_for_character(character_id)

    def merge_character(self, source_character_id: int, target_character_id: int) -> CharacterRecord:
        record = self.repository.merge_character(source_character_id, target_character_id)
        self._sync_statistics()
        return record

    def merge_series(self, source_series_id: int, target_series_id: int) -> SeriesRecord:
        record = self.repository.merge_series(source_series_id, target_series_id)
        self._sync_statistics()
        return record

    def import_characters(self, payloads: list[dict], *, job_id: str | None = None, resumed: bool = False) -> list[CharacterRecord]:
        resolved_id = job_id or str(uuid4())
        checkpoint = self._checkpoints.get(resolved_id, WorkerCheckpoint(task_type=WorkerTaskType.IMPORT_CHARACTERS, processed=0, total=len(payloads)))
        checkpoint.total = len(payloads)
        self._checkpoints[resolved_id] = checkpoint

        imported: list[CharacterRecord] = []
        start = checkpoint.processed if resumed else 0
        for index in range(start, len(payloads)):
            if resolved_id in self._cancel_requested:
                break
            imported.append(self.create_character(**payloads[index]))
            checkpoint.processed = index + 1
            self._emit(
                WorkerProgress(
                    job_id=resolved_id,
                    task_type=WorkerTaskType.IMPORT_CHARACTERS,
                    processed=checkpoint.processed,
                    total=checkpoint.total,
                    message="Imported character records.",
                )
            )
        self.statistics.record_import(len(imported))
        return imported

    def import_series(self, payloads: list[dict], *, job_id: str | None = None, resumed: bool = False) -> list[SeriesRecord]:
        resolved_id = job_id or str(uuid4())
        checkpoint = self._checkpoints.get(resolved_id, WorkerCheckpoint(task_type=WorkerTaskType.IMPORT_SERIES, processed=0, total=len(payloads)))
        checkpoint.total = len(payloads)
        self._checkpoints[resolved_id] = checkpoint

        imported: list[SeriesRecord] = []
        start = checkpoint.processed if resumed else 0
        for index in range(start, len(payloads)):
            if resolved_id in self._cancel_requested:
                break
            imported.append(self.create_series(**payloads[index]))
            checkpoint.processed = index + 1
            self._emit(
                WorkerProgress(
                    job_id=resolved_id,
                    task_type=WorkerTaskType.IMPORT_SERIES,
                    processed=checkpoint.processed,
                    total=checkpoint.total,
                    message="Imported series records.",
                )
            )
        self.statistics.record_import(len(imported))
        return imported

    def merge_database(self, payload: dict, *, job_id: str | None = None, resumed: bool = False) -> dict:
        resolved_id = job_id or str(uuid4())
        series_payloads = list(payload.get("series", []))
        character_payloads = list(payload.get("characters", []))

        imported_series = self.import_series(series_payloads, job_id=f"{resolved_id}-series", resumed=resumed)
        imported_characters = self.import_characters(character_payloads, job_id=f"{resolved_id}-characters", resumed=resumed)
        report = self.validate_database()
        return {
            "series": imported_series,
            "characters": imported_characters,
            "validation": report,
        }

    def validate_database(self, *, strict: bool = False):
        report = self.repository.validate()
        duplicates = report.duplicate_aliases + report.duplicate_canonical_names_in_series
        self.statistics.record_validation(duplicates)
        if strict and not report.valid:
            raise CharacterDatabaseValidationError("Character database validation failed in strict mode.")
        return report

    def request_cancel(self, job_id: str) -> None:
        self._cancel_requested.add(job_id)

    def checkpoint_for(self, job_id: str) -> WorkerCheckpoint:
        checkpoint = self._checkpoints.get(job_id)
        if checkpoint is None:
            return WorkerCheckpoint(task_type=WorkerTaskType.VALIDATE, processed=0, total=0)
        return WorkerCheckpoint(task_type=checkpoint.task_type, processed=checkpoint.processed, total=checkpoint.total)

    def _sync_statistics(self) -> None:
        self.statistics.sync_counts(
            characters=len(self.repository.list_characters()),
            series=len(self.repository.list_series()),
            aliases=self.repository.alias_count(),
            relationships=self.repository.relationship_count(),
        )

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)
