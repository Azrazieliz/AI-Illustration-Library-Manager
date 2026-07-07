from __future__ import annotations

from engine.character_database.character_database_models import (
    AliasKind,
    AliasRecord,
    CharacterRecord,
    CharacterRelationship,
    DisambiguationEntry,
    SeriesRecord,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)


class CharacterDatabaseBuilder:
    """Builder for character database records and validation payloads."""

    def build_alias_record(self, *, character_id: int, value: str, kind: AliasKind = AliasKind.ALIAS) -> AliasRecord:
        normalized = value.strip().casefold()
        return AliasRecord(character_id=character_id, value=value.strip(), normalized_value=normalized, kind=kind)

    def build_character_record(
        self,
        *,
        character_id: int,
        series_id: int | None,
        canonical_name: str,
        localized_names: list[str] | None = None,
        japanese_name: str | None = None,
        english_name: str | None = None,
        romaji: str | None = None,
        aliases: list[str] | None = None,
        nicknames: list[str] | None = None,
        alternative_spellings: list[str] | None = None,
        abbreviations: list[str] | None = None,
        gender: str | None = None,
        description: str = "",
        relationships: list[CharacterRelationship] | None = None,
    ) -> CharacterRecord:
        return CharacterRecord(
            character_id=character_id,
            series_id=series_id,
            canonical_name=canonical_name.strip(),
            localized_names=list(localized_names or []),
            japanese_name=japanese_name,
            english_name=english_name,
            romaji=romaji,
            aliases=list(aliases or []),
            nicknames=list(nicknames or []),
            alternative_spellings=list(alternative_spellings or []),
            abbreviations=list(abbreviations or []),
            gender=gender,
            description=description,
            relationships=list(relationships or []),
        )

    def build_series_record(
        self,
        *,
        series_id: int,
        canonical_title: str,
        aliases: list[str] | None = None,
        japanese_title: str | None = None,
        english_title: str | None = None,
        romaji: str | None = None,
        franchise: str | None = None,
        parent_series_id: int | None = None,
        spin_off_ids: list[int] | None = None,
        sequel_ids: list[int] | None = None,
        prequel_ids: list[int] | None = None,
    ) -> SeriesRecord:
        return SeriesRecord(
            series_id=series_id,
            canonical_title=canonical_title.strip(),
            aliases=list(aliases or []),
            japanese_title=japanese_title,
            english_title=english_title,
            romaji=romaji,
            franchise=franchise,
            parent_series_id=parent_series_id,
            spin_off_ids=list(spin_off_ids or []),
            sequel_ids=list(sequel_ids or []),
            prequel_ids=list(prequel_ids or []),
        )

    def build_disambiguation_entry(self, *, character: CharacterRecord, series_title: str | None) -> DisambiguationEntry:
        return DisambiguationEntry(
            character_id=character.character_id,
            canonical_name=character.canonical_name,
            series_id=character.series_id,
            series_title=series_title,
        )

    def build_validation_issue(self, *, severity: ValidationSeverity, code: str, message: str) -> ValidationIssue:
        return ValidationIssue(severity=severity, code=code, message=message)

    def build_validation_report(
        self,
        *,
        issues: list[ValidationIssue],
        duplicate_ids: int,
        duplicate_aliases: int,
        broken_references: int,
        circular_series_links: int,
        circular_relationship_graphs: int,
        invalid_aliases: int,
        duplicate_canonical_names_in_series: int,
    ) -> ValidationReport:
        has_error = any(item.severity is ValidationSeverity.ERROR for item in issues)
        return ValidationReport(
            valid=not has_error,
            issues=list(issues),
            duplicate_ids=max(0, duplicate_ids),
            duplicate_aliases=max(0, duplicate_aliases),
            broken_references=max(0, broken_references),
            circular_series_links=max(0, circular_series_links),
            circular_relationship_graphs=max(0, circular_relationship_graphs),
            invalid_aliases=max(0, invalid_aliases),
            duplicate_canonical_names_in_series=max(0, duplicate_canonical_names_in_series),
        )
