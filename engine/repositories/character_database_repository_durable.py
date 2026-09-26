from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any

from sqlalchemy import delete, select, update

from engine.character_database.character_database_models import CharacterRecord, CharacterRelationship, RelationshipType, SeriesRecord
from engine.database.models.character_database_state import CharacterDatabaseStateRecord
from engine.database.session import session_scope
from engine.repositories.character_database_repository import InMemoryCharacterDatabaseRepository


class DurableCharacterDatabaseRepository(InMemoryCharacterDatabaseRepository):
    """Versioned persistence for canonical character and series identity records."""

    _state_key = "default"
    _state_lock = RLock()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lock = self._state_lock
        self._state_version: int | None = None
        self._load_state()

    @classmethod
    def reset_state(cls) -> None:
        with cls._state_lock, session_scope() as session:
            session.execute(delete(CharacterDatabaseStateRecord))

    def create_series(self, **kwargs: Any) -> SeriesRecord:
        with self._lock:
            result = super().create_series(**kwargs)
            self._persist_state()
            return result

    def create_character(self, **kwargs: Any) -> CharacterRecord:
        with self._lock:
            result = super().create_character(**kwargs)
            self._persist_state()
            return result

    def merge_character(self, source_character_id: int, target_character_id: int) -> CharacterRecord:
        with self._lock:
            result = super().merge_character(source_character_id, target_character_id)
            self._persist_state()
            return result

    def merge_series(self, source_series_id: int, target_series_id: int) -> SeriesRecord:
        with self._lock:
            result = super().merge_series(source_series_id, target_series_id)
            self._persist_state()
            return result

    def find_character(self, identifier: int) -> CharacterRecord | None:
        with self._lock:
            return super().find_character(identifier)

    def find_series(self, identifier: int) -> SeriesRecord | None:
        with self._lock:
            return super().find_series(identifier)

    def list_characters(self) -> list[CharacterRecord]:
        with self._lock:
            return super().list_characters()

    def list_series(self) -> list[SeriesRecord]:
        with self._lock:
            return super().list_series()

    def search_characters(self, query: str, *, fuzzy: bool = True) -> list[CharacterRecord]:
        with self._lock:
            return super().search_characters(query, fuzzy=fuzzy)

    def search_series(self, query: str, *, fuzzy: bool = True) -> list[SeriesRecord]:
        with self._lock:
            return super().search_series(query, fuzzy=fuzzy)

    def find_alias(self, alias: str) -> list[CharacterRecord]:
        with self._lock:
            return super().find_alias(alias)

    def find_series_alias(self, alias: str) -> list[SeriesRecord]:
        with self._lock:
            return super().find_series_alias(alias)

    def find_characters_by_series(self, series_id: int) -> list[CharacterRecord]:
        with self._lock:
            return super().find_characters_by_series(series_id)

    def find_series_for_character(self, character_id: int) -> SeriesRecord | None:
        with self._lock:
            return super().find_series_for_character(character_id)

    def validate(self):
        with self._lock:
            return super().validate()

    def relationship_count(self) -> int:
        with self._lock:
            return super().relationship_count()

    def alias_count(self) -> int:
        with self._lock:
            return super().alias_count()

    def _load_state(self) -> None:
        with self._lock, session_scope() as session:
            row = session.scalar(
                select(CharacterDatabaseStateRecord).where(CharacterDatabaseStateRecord.state_key == self._state_key)
            )
            if row is None:
                return
            self._state_version = row.version
            self._restore_state(dict(row.state_payload or {}))

    def _persist_state(self) -> None:
        payload = self._state_payload()
        with session_scope() as session:
            row = session.scalar(
                select(CharacterDatabaseStateRecord).where(CharacterDatabaseStateRecord.state_key == self._state_key)
            )
            if row is None:
                if self._state_version is not None:
                    raise RuntimeError("Character-database state was removed while this repository was active")
                row = CharacterDatabaseStateRecord(state_key=self._state_key, state_payload=payload)
                session.add(row)
                session.flush()
                self._state_version = row.version
                return
            if self._state_version is None or row.version != self._state_version:
                raise RuntimeError("Character-database state changed in another repository instance; reload before writing")
            result = session.execute(
                update(CharacterDatabaseStateRecord)
                .where(
                    CharacterDatabaseStateRecord.id == row.id,
                    CharacterDatabaseStateRecord.version == self._state_version,
                )
                .values(
                    state_payload=payload,
                    version=CharacterDatabaseStateRecord.version + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if int(result.rowcount or 0) != 1:
                raise RuntimeError("Character-database state changed concurrently; retry the operation")
            self._state_version += 1

    def _state_payload(self) -> dict[str, Any]:
        return {
            "series": [
                {
                    "series_id": record.series_id,
                    "canonical_title": record.canonical_title,
                    "aliases": list(record.aliases),
                    "japanese_title": record.japanese_title,
                    "english_title": record.english_title,
                    "romaji": record.romaji,
                    "franchise": record.franchise,
                    "parent_series_id": record.parent_series_id,
                    "spin_off_ids": list(record.spin_off_ids),
                    "sequel_ids": list(record.sequel_ids),
                    "prequel_ids": list(record.prequel_ids),
                }
                for record in self._series.values()
            ],
            "characters": [
                {
                    "character_id": record.character_id,
                    "series_id": record.series_id,
                    "canonical_name": record.canonical_name,
                    "localized_names": list(record.localized_names),
                    "japanese_name": record.japanese_name,
                    "english_name": record.english_name,
                    "romaji": record.romaji,
                    "aliases": list(record.aliases),
                    "nicknames": list(record.nicknames),
                    "alternative_spellings": list(record.alternative_spellings),
                    "abbreviations": list(record.abbreviations),
                    "gender": record.gender,
                    "description": record.description,
                    "relationships": [
                        {
                            "source_character_id": relationship.source_character_id,
                            "target_character_id": relationship.target_character_id,
                            "relation": relationship.relation.value,
                        }
                        for relationship in record.relationships
                    ],
                }
                for record in self._characters.values()
            ],
        }

    def _restore_state(self, payload: dict[str, Any]) -> None:
        self._characters = {}
        self._series = {}
        self._alias_to_character_ids = {}
        self._series_lookup = {}

        for item in payload.get("series", []):
            if not isinstance(item, dict):
                continue
            record = SeriesRecord(
                series_id=int(item["series_id"]),
                canonical_title=str(item.get("canonical_title", "")),
                aliases=[str(value) for value in item.get("aliases", [])],
                japanese_title=item.get("japanese_title"),
                english_title=item.get("english_title"),
                romaji=item.get("romaji"),
                franchise=item.get("franchise"),
                parent_series_id=item.get("parent_series_id"),
                spin_off_ids=[int(value) for value in item.get("spin_off_ids", [])],
                sequel_ids=[int(value) for value in item.get("sequel_ids", [])],
                prequel_ids=[int(value) for value in item.get("prequel_ids", [])],
            )
            self._series[record.series_id] = record
            self._index_series_aliases(record)

        for item in payload.get("characters", []):
            if not isinstance(item, dict):
                continue
            record = CharacterRecord(
                character_id=int(item["character_id"]),
                series_id=item.get("series_id"),
                canonical_name=str(item.get("canonical_name", "")),
                localized_names=[str(value) for value in item.get("localized_names", [])],
                japanese_name=item.get("japanese_name"),
                english_name=item.get("english_name"),
                romaji=item.get("romaji"),
                aliases=[str(value) for value in item.get("aliases", [])],
                nicknames=[str(value) for value in item.get("nicknames", [])],
                alternative_spellings=[str(value) for value in item.get("alternative_spellings", [])],
                abbreviations=[str(value) for value in item.get("abbreviations", [])],
                gender=item.get("gender"),
                description=str(item.get("description", "")),
                relationships=[
                    CharacterRelationship(
                        source_character_id=int(relationship.get("source_character_id", 0)),
                        target_character_id=int(relationship.get("target_character_id", 0)),
                        relation=RelationshipType(str(relationship.get("relation", RelationshipType.BELONGS_TO.value))),
                    )
                    for relationship in item.get("relationships", [])
                    if isinstance(relationship, dict)
                ],
            )
            self._characters[record.character_id] = record
            self._index_character_aliases(record)