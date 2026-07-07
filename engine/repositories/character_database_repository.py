from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher, get_close_matches

from engine.character_database.character_database_builder import CharacterDatabaseBuilder
from engine.character_database.character_database_exceptions import CharacterNotFoundError, SeriesNotFoundError
from engine.character_database.character_database_models import (
    AliasKind,
    CharacterRecord,
    CharacterRelationship,
    RelationshipType,
    SeriesRecord,
    ValidationSeverity,
)


class CharacterDatabaseRepository:
    """In-memory canonical character and series identity store."""

    def __init__(self, *, builder: CharacterDatabaseBuilder | None = None) -> None:
        self.builder = builder or CharacterDatabaseBuilder()
        self._characters: dict[int, CharacterRecord] = {}
        self._series: dict[int, SeriesRecord] = {}
        self._alias_to_character_ids: dict[str, set[int]] = {}

    def create_series(self, **kwargs) -> SeriesRecord:
        record = kwargs.get("record")
        if record is None:
            record = self.builder.build_series_record(**kwargs)
        series_id = record.series_id
        if series_id in self._series:
            raise ValueError(f"Series id already exists: {series_id}")
        self._series[series_id] = deepcopy(record)
        return deepcopy(self._series[series_id])

    def create_character(self, **kwargs) -> CharacterRecord:
        record = kwargs.get("record")
        if record is None:
            record = self.builder.build_character_record(**kwargs)
        character_id = record.character_id
        if character_id in self._characters:
            raise ValueError(f"Character id already exists: {character_id}")
        if record.series_id is not None and record.series_id not in self._series:
            raise SeriesNotFoundError(f"Unknown series id: {record.series_id}")
        self._characters[character_id] = deepcopy(record)
        self._index_character_aliases(self._characters[character_id])
        return deepcopy(self._characters[character_id])

    def find_character(self, identifier: int) -> CharacterRecord | None:
        record = self._characters.get(identifier)
        return deepcopy(record) if record is not None else None

    def find_series(self, identifier: int) -> SeriesRecord | None:
        record = self._series.get(identifier)
        return deepcopy(record) if record is not None else None

    def list_characters(self) -> list[CharacterRecord]:
        return [deepcopy(self._characters[key]) for key in sorted(self._characters.keys())]

    def list_series(self) -> list[SeriesRecord]:
        return [deepcopy(self._series[key]) for key in sorted(self._series.keys())]

    def search_characters(self, query: str, *, fuzzy: bool = True) -> list[CharacterRecord]:
        query_norm = query.strip().casefold()
        if not query_norm:
            return []

        exact_hits: dict[int, CharacterRecord] = {}
        for record in self._characters.values():
            if self._character_matches(record, query_norm):
                exact_hits[record.character_id] = record

        if exact_hits:
            return [deepcopy(exact_hits[key]) for key in sorted(exact_hits.keys())]

        if not fuzzy:
            return []

        score_hits: list[tuple[float, int]] = []
        for record in self._characters.values():
            candidates = self._character_search_terms(record)
            score = max((SequenceMatcher(None, query_norm, value).ratio() for value in candidates), default=0.0)
            if score >= 0.70:
                score_hits.append((score, record.character_id))

        score_hits.sort(key=lambda item: (-item[0], item[1]))
        return [deepcopy(self._characters[item[1]]) for item in score_hits]

    def search_series(self, query: str, *, fuzzy: bool = True) -> list[SeriesRecord]:
        query_norm = query.strip().casefold()
        if not query_norm:
            return []

        exact_hits = []
        for record in self._series.values():
            terms = self._series_search_terms(record)
            if any(query_norm in value for value in terms):
                exact_hits.append(record)

        if exact_hits:
            exact_hits.sort(key=lambda item: item.series_id)
            return [deepcopy(item) for item in exact_hits]

        if not fuzzy:
            return []

        title_map = {record.series_id: record.canonical_title for record in self._series.values()}
        close = get_close_matches(query, list(title_map.values()), n=8, cutoff=0.7)
        ids = [sid for sid, title in title_map.items() if title in close]
        return [deepcopy(self._series[sid]) for sid in sorted(ids)]

    def find_alias(self, alias: str) -> list[CharacterRecord]:
        alias_norm = alias.strip().casefold()
        ids = sorted(self._alias_to_character_ids.get(alias_norm, set()))
        return [deepcopy(self._characters[item]) for item in ids if item in self._characters]

    def find_characters_by_series(self, series_id: int) -> list[CharacterRecord]:
        rows = [item for item in self._characters.values() if item.series_id == series_id]
        rows.sort(key=lambda item: item.character_id)
        return [deepcopy(item) for item in rows]

    def find_series_for_character(self, character_id: int) -> SeriesRecord | None:
        character = self._characters.get(character_id)
        if character is None or character.series_id is None:
            return None
        series = self._series.get(character.series_id)
        return deepcopy(series) if series is not None else None

    def merge_character(self, source_character_id: int, target_character_id: int) -> CharacterRecord:
        if source_character_id == target_character_id:
            raise ValueError("Source and target character ids must be different.")
        source = self._characters.get(source_character_id)
        target = self._characters.get(target_character_id)
        if source is None:
            raise CharacterNotFoundError(f"Unknown source character id: {source_character_id}")
        if target is None:
            raise CharacterNotFoundError(f"Unknown target character id: {target_character_id}")

        self._remove_alias_index(source)
        self._remove_alias_index(target)

        target.localized_names = self._dedupe_text(target.localized_names + source.localized_names)
        target.aliases = self._dedupe_text(target.aliases + source.aliases)
        target.nicknames = self._dedupe_text(target.nicknames + source.nicknames)
        target.alternative_spellings = self._dedupe_text(target.alternative_spellings + source.alternative_spellings)
        target.abbreviations = self._dedupe_text(target.abbreviations + source.abbreviations)
        target.relationships = self._merge_relationships(target.relationships, source.relationships)

        for record in self._characters.values():
            updated = []
            for rel in record.relationships:
                src = target_character_id if rel.source_character_id == source_character_id else rel.source_character_id
                dst = target_character_id if rel.target_character_id == source_character_id else rel.target_character_id
                updated.append(CharacterRelationship(source_character_id=src, target_character_id=dst, relation=rel.relation))
            record.relationships = self._merge_relationships([], updated)

        del self._characters[source_character_id]
        self._index_character_aliases(target)
        return deepcopy(target)

    def merge_series(self, source_series_id: int, target_series_id: int) -> SeriesRecord:
        if source_series_id == target_series_id:
            raise ValueError("Source and target series ids must be different.")
        source = self._series.get(source_series_id)
        target = self._series.get(target_series_id)
        if source is None:
            raise SeriesNotFoundError(f"Unknown source series id: {source_series_id}")
        if target is None:
            raise SeriesNotFoundError(f"Unknown target series id: {target_series_id}")

        target.aliases = self._dedupe_text(target.aliases + source.aliases)
        target.spin_off_ids = self._dedupe_ints(target.spin_off_ids + source.spin_off_ids)
        target.sequel_ids = self._dedupe_ints(target.sequel_ids + source.sequel_ids)
        target.prequel_ids = self._dedupe_ints(target.prequel_ids + source.prequel_ids)

        for character in self._characters.values():
            if character.series_id == source_series_id:
                character.series_id = target_series_id

        for series in self._series.values():
            if series.parent_series_id == source_series_id:
                series.parent_series_id = target_series_id
            series.spin_off_ids = [target_series_id if item == source_series_id else item for item in series.spin_off_ids]
            series.sequel_ids = [target_series_id if item == source_series_id else item for item in series.sequel_ids]
            series.prequel_ids = [target_series_id if item == source_series_id else item for item in series.prequel_ids]

        del self._series[source_series_id]
        return deepcopy(target)

    def validate(self):
        issues = []
        duplicate_aliases = self._count_duplicate_aliases()
        invalid_aliases = self._count_invalid_aliases()
        broken_references = self._count_broken_references()
        circular_series_links = self._count_circular_series_links()
        circular_relationship_graphs = self._count_circular_relationship_graphs()
        duplicate_names = self._count_duplicate_canonical_names_in_series()

        if duplicate_aliases > 0:
            issues.append(self.builder.build_validation_issue(severity=ValidationSeverity.ERROR, code="duplicate_aliases", message="Duplicate aliases resolve to multiple character ids."))
        if invalid_aliases > 0:
            issues.append(self.builder.build_validation_issue(severity=ValidationSeverity.ERROR, code="invalid_aliases", message="Alias values include empty or whitespace-only entries."))
        if broken_references > 0:
            issues.append(self.builder.build_validation_issue(severity=ValidationSeverity.ERROR, code="broken_references", message="Series or relationship references are broken."))
        if circular_series_links > 0:
            issues.append(self.builder.build_validation_issue(severity=ValidationSeverity.ERROR, code="circular_series_links", message="Circular links detected in series hierarchy."))
        if circular_relationship_graphs > 0:
            issues.append(self.builder.build_validation_issue(severity=ValidationSeverity.ERROR, code="circular_relationship_graphs", message="Circular character relationship graph detected."))
        if duplicate_names > 0:
            issues.append(self.builder.build_validation_issue(severity=ValidationSeverity.ERROR, code="duplicate_canonical_names_in_series", message="Duplicate canonical names exist within the same series."))

        return self.builder.build_validation_report(
            issues=issues,
            duplicate_ids=0,
            duplicate_aliases=duplicate_aliases,
            broken_references=broken_references,
            circular_series_links=circular_series_links,
            circular_relationship_graphs=circular_relationship_graphs,
            invalid_aliases=invalid_aliases,
            duplicate_canonical_names_in_series=duplicate_names,
        )

    def relationship_count(self) -> int:
        return sum(len(item.relationships) for item in self._characters.values())

    def alias_count(self) -> int:
        return sum(len(item) for item in self._alias_to_character_ids.values())

    def _character_matches(self, record: CharacterRecord, query_norm: str) -> bool:
        if query_norm.isdigit() and int(query_norm) == record.character_id:
            return True
        if record.series_id is not None and query_norm.isdigit() and int(query_norm) == record.series_id:
            return True
        return any(query_norm in value for value in self._character_search_terms(record))

    def _character_search_terms(self, record: CharacterRecord) -> list[str]:
        values = [record.canonical_name]
        values.extend(record.localized_names)
        if record.japanese_name:
            values.append(record.japanese_name)
        if record.english_name:
            values.append(record.english_name)
        if record.romaji:
            values.append(record.romaji)
        values.extend(record.aliases)
        values.extend(record.nicknames)
        values.extend(record.alternative_spellings)
        values.extend(record.abbreviations)
        return [item.strip().casefold() for item in values if item and item.strip()]

    def _series_search_terms(self, record: SeriesRecord) -> list[str]:
        values = [record.canonical_title]
        values.extend(record.aliases)
        if record.japanese_title:
            values.append(record.japanese_title)
        if record.english_title:
            values.append(record.english_title)
        if record.romaji:
            values.append(record.romaji)
        if record.franchise:
            values.append(record.franchise)
        return [item.strip().casefold() for item in values if item and item.strip()]

    def _index_character_aliases(self, record: CharacterRecord) -> None:
        for value in self._all_alias_values(record):
            key = value.strip().casefold()
            self._alias_to_character_ids.setdefault(key, set()).add(record.character_id)

    def _remove_alias_index(self, record: CharacterRecord) -> None:
        for value in self._all_alias_values(record):
            key = value.strip().casefold()
            ids = self._alias_to_character_ids.get(key)
            if ids is None:
                continue
            ids.discard(record.character_id)
            if not ids:
                del self._alias_to_character_ids[key]

    def _all_alias_values(self, record: CharacterRecord) -> list[str]:
        values = [record.canonical_name]
        values.extend(record.localized_names)
        if record.japanese_name:
            values.append(record.japanese_name)
        if record.english_name:
            values.append(record.english_name)
        if record.romaji:
            values.append(record.romaji)
        values.extend(record.aliases)
        values.extend(record.nicknames)
        values.extend(record.alternative_spellings)
        values.extend(record.abbreviations)
        return [item for item in values if isinstance(item, str)]

    def _merge_relationships(self, left: list[CharacterRelationship], right: list[CharacterRelationship]) -> list[CharacterRelationship]:
        merged = []
        seen = set()
        for item in list(left) + list(right):
            key = (item.source_character_id, item.target_character_id, item.relation.value)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def _dedupe_text(self, values: list[str]) -> list[str]:
        out = []
        seen = set()
        for value in values:
            normalized = value.strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(value.strip())
        return out

    def _dedupe_ints(self, values: list[int]) -> list[int]:
        out = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _count_duplicate_aliases(self) -> int:
        return sum(1 for ids in self._alias_to_character_ids.values() if len(ids) > 1)

    def _count_invalid_aliases(self) -> int:
        invalid = 0
        for record in self._characters.values():
            for item in self._all_alias_values(record):
                if not item.strip():
                    invalid += 1
        return invalid

    def _count_broken_references(self) -> int:
        broken = 0
        for record in self._characters.values():
            if record.series_id is not None and record.series_id not in self._series:
                broken += 1
            for rel in record.relationships:
                if rel.source_character_id not in self._characters or rel.target_character_id not in self._characters:
                    broken += 1
        for record in self._series.values():
            linked = []
            if record.parent_series_id is not None:
                linked.append(record.parent_series_id)
            linked.extend(record.spin_off_ids)
            linked.extend(record.sequel_ids)
            linked.extend(record.prequel_ids)
            for series_id in linked:
                if series_id not in self._series:
                    broken += 1
        return broken

    def _count_circular_series_links(self) -> int:
        circular = 0

        def walk(start_id: int, current_id: int, path: set[int]) -> bool:
            if current_id in path:
                return True
            series = self._series.get(current_id)
            if series is None:
                return False
            next_id = series.parent_series_id
            if next_id is None:
                return False
            next_path = set(path)
            next_path.add(current_id)
            return walk(start_id, next_id, next_path)

        for series_id in self._series:
            if walk(series_id, series_id, set()):
                circular += 1
        return circular

    def _count_circular_relationship_graphs(self) -> int:
        edges: dict[int, set[int]] = {}
        for record in self._characters.values():
            for rel in record.relationships:
                if rel.relation not in {RelationshipType.PARENT, RelationshipType.CHILD, RelationshipType.BELONGS_TO}:
                    continue
                edges.setdefault(rel.source_character_id, set()).add(rel.target_character_id)

        visiting = set()
        visited = set()
        cycles = 0

        def dfs(node: int) -> None:
            nonlocal cycles
            if node in visiting:
                cycles += 1
                return
            if node in visited:
                return
            visiting.add(node)
            for nxt in edges.get(node, set()):
                dfs(nxt)
            visiting.discard(node)
            visited.add(node)

        for node in edges:
            dfs(node)
        return cycles

    def _count_duplicate_canonical_names_in_series(self) -> int:
        seen: dict[tuple[int | None, str], int] = {}
        duplicates = 0
        for record in self._characters.values():
            key = (record.series_id, record.canonical_name.strip().casefold())
            seen[key] = seen.get(key, 0) + 1
        for count in seen.values():
            if count > 1:
                duplicates += 1
        return duplicates
