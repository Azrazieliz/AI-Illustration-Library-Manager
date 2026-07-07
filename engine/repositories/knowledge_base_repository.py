from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from threading import Lock
from typing import Any

from engine.knowledge_base.knowledge_base_builder import KnowledgeBaseBuilder
from engine.knowledge_base.knowledge_base_exceptions import (
    KnowledgeBaseDuplicateError,
    KnowledgeBaseImportError,
    KnowledgeBaseNotFoundError,
)
from engine.knowledge_base.knowledge_base_models import (
    KnowledgeBaseCandidate,
    KnowledgeBaseCharacter,
    KnowledgeBaseDataset,
    KnowledgeBaseDatasetStatus,
    KnowledgeBaseImportFormat,
    KnowledgeBaseRecordKind,
    KnowledgeBaseReferenceImage,
    KnowledgeBaseRelationship,
    KnowledgeBaseSeries,
    KnowledgeBaseTrainingSample,
    KnowledgeBaseValidationReport,
)
from engine.review.review_models import ReviewItem, ReviewStatus


class KnowledgeBaseRepository:
    """Canonical knowledge store for trusted training data."""

    def __init__(self, *, builder: KnowledgeBaseBuilder | None = None) -> None:
        self.builder = builder or KnowledgeBaseBuilder()
        self._lock = Lock()
        self._datasets: dict[int, KnowledgeBaseDataset] = {}
        self._series: dict[int, KnowledgeBaseSeries] = {}
        self._characters: dict[int, KnowledgeBaseCharacter] = {}
        self._reference_images: dict[int, KnowledgeBaseReferenceImage] = {}
        self._training_samples: dict[int, KnowledgeBaseTrainingSample] = {}
        self._next_dataset_id = 1
        self._next_series_id = 1
        self._next_character_id = 1
        self._next_reference_image_id = 1
        self._next_training_sample_id = 1
        self._search_cache: dict[str, list[KnowledgeBaseCandidate]] = {}

    # ------------------------------------------------------------------
    # Dataset lifecycle
    # ------------------------------------------------------------------
    def create_dataset(
        self,
        *,
        name: str,
        description: str = "",
        version: str = "1.0",
        status: KnowledgeBaseDatasetStatus = KnowledgeBaseDatasetStatus.ACTIVE,
        tags: list[str] | None = None,
        notes: str = "",
        dataset_id: int | None = None,
    ) -> KnowledgeBaseDataset:
        with self._lock:
            identifier = dataset_id or self._next_dataset_id
            if identifier in self._datasets:
                raise KnowledgeBaseDuplicateError(f"Dataset id already exists: {identifier}")
            self._next_dataset_id = max(self._next_dataset_id, identifier + 1)
            dataset = self.builder.build_dataset_record(
                dataset_id=identifier,
                name=name,
                description=description,
                version=version,
                status=status,
                tags=tags,
                notes=notes,
            )
            self._datasets[identifier] = dataset
            return self._clone(dataset)

    def list_datasets(self) -> list[KnowledgeBaseDataset]:
        return [self._clone(item) for item in sorted(self._datasets.values(), key=lambda item: item.dataset_id)]

    def find_dataset(self, dataset_id: int) -> KnowledgeBaseDataset | None:
        record = self._datasets.get(dataset_id)
        return self._clone(record) if record is not None else None

    def update_dataset(self, dataset_id: int, **changes: Any) -> KnowledgeBaseDataset:
        with self._lock:
            dataset = self._datasets.get(dataset_id)
            if dataset is None:
                raise KnowledgeBaseNotFoundError(f"Dataset not found: {dataset_id}")
            for key, value in changes.items():
                if hasattr(dataset, key):
                    setattr(dataset, key, value)
            dataset.updated_at = datetime.now(timezone.utc)
            self._recalculate_dataset_counts(dataset_id)
            return self._clone(dataset)

    def delete_dataset(self, dataset_id: int) -> None:
        with self._lock:
            if dataset_id not in self._datasets:
                raise KnowledgeBaseNotFoundError(f"Dataset not found: {dataset_id}")
            series_ids = [item.canonical_id for item in self._series.values() if item.dataset_id == dataset_id]
            character_ids = [item.canonical_id for item in self._characters.values() if item.dataset_id == dataset_id]
            reference_ids = [reference.image_id for character in self._characters.values() if character.dataset_id == dataset_id for reference in character.reference_images]
            sample_ids = [sample.sample_id for character in self._characters.values() if character.dataset_id == dataset_id for sample in character.approved_examples]
            for identifier in series_ids:
                self._series.pop(identifier, None)
            for identifier in character_ids:
                self._characters.pop(identifier, None)
            for identifier in reference_ids:
                self._reference_images.pop(identifier, None)
            for identifier in sample_ids:
                self._training_samples.pop(identifier, None)
            del self._datasets[dataset_id]
            self._search_cache.clear()

    # ------------------------------------------------------------------
    # Series and characters
    # ------------------------------------------------------------------
    def create_series(
        self,
        *,
        dataset_id: int,
        canonical_id: int | None = None,
        title: str,
        aliases: list[str] | None = None,
        localized_titles: list[str] | None = None,
        description: str = "",
        parent_series_id: int | None = None,
        related_series_ids: list[int] | None = None,
        character_ids: list[int] | None = None,
        tags: list[str] | None = None,
        notes: str = "",
    ) -> KnowledgeBaseSeries:
        with self._lock:
            self._require_dataset(dataset_id)
            identifier = canonical_id or self._next_series_id
            if identifier in self._series:
                raise KnowledgeBaseDuplicateError(f"Series id already exists: {identifier}")
            self._next_series_id = max(self._next_series_id, identifier + 1)
            record = self.builder.build_series_record(
                dataset_id=dataset_id,
                canonical_id=identifier,
                title=title,
                aliases=aliases,
                localized_titles=localized_titles,
                description=description,
                parent_series_id=parent_series_id,
                related_series_ids=related_series_ids,
                character_ids=character_ids,
                tags=tags,
                notes=notes,
            )
            self._series[identifier] = record
            self._recalculate_dataset_counts(dataset_id)
            self._search_cache.clear()
            return self._clone(record)

    def create_character(
        self,
        *,
        dataset_id: int,
        canonical_id: int | None = None,
        series_id: int | None,
        canonical_name: str,
        aliases: list[str] | None = None,
        localized_names: list[str] | None = None,
        romaji: str | None = None,
        japanese: str | None = None,
        english: str | None = None,
        gender: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
        notes: str = "",
        confidence_score: float = 0.0,
        training_priority: float = 1.0,
    ) -> KnowledgeBaseCharacter:
        with self._lock:
            self._require_dataset(dataset_id)
            if series_id is not None and series_id not in self._series:
                raise KnowledgeBaseNotFoundError(f"Series not found: {series_id}")
            identifier = canonical_id or self._next_character_id
            if identifier in self._characters:
                raise KnowledgeBaseDuplicateError(f"Character id already exists: {identifier}")
            self._next_character_id = max(self._next_character_id, identifier + 1)
            record = self.builder.build_character_record(
                dataset_id=dataset_id,
                canonical_id=identifier,
                series_id=series_id,
                canonical_name=canonical_name,
                aliases=aliases,
                localized_names=localized_names,
                romaji=romaji,
                japanese=japanese,
                english=english,
                gender=gender,
                description=description,
                tags=tags,
                notes=notes,
                confidence_score=confidence_score,
                training_priority=training_priority,
            )
            self._characters[identifier] = record
            if series_id is not None:
                self._series[series_id].character_ids = self._dedupe_ints(self._series[series_id].character_ids + [identifier])
            self._recalculate_dataset_counts(dataset_id)
            self._search_cache.clear()
            return self._clone(record)

    def add_relationship(
        self,
        *,
        character_id: int,
        relation: str,
        target_kind: KnowledgeBaseRecordKind,
        target_id: int,
        confidence: float = 0.0,
        notes: str = "",
    ) -> KnowledgeBaseRelationship:
        with self._lock:
            character = self._characters.get(character_id)
            if character is None:
                raise KnowledgeBaseNotFoundError(f"Character not found: {character_id}")
            relationship = self.builder.build_relationship_record(
                relation=relation,
                target_kind=target_kind,
                target_id=target_id,
                confidence=confidence,
                notes=notes,
            )
            character.relationships.append(relationship)
            character.updated_at = datetime.now(timezone.utc)
            self._recalculate_dataset_counts(character.dataset_id)
            return self._clone(relationship)

    def add_reference_image(
        self,
        *,
        character_id: int,
        image_id: int | None = None,
        path: str | Path,
        quality_score: float = 0.0,
        pose_type: str | None = None,
        expression: str | None = None,
        outfit: str | None = None,
        source: str | None = None,
        approved: bool = True,
        embedding_id: int | None = None,
        hash_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeBaseReferenceImage:
        with self._lock:
            character = self._characters.get(character_id)
            if character is None:
                raise KnowledgeBaseNotFoundError(f"Character not found: {character_id}")
            identifier = image_id or self._next_reference_image_id
            if identifier in self._reference_images:
                raise KnowledgeBaseDuplicateError(f"Reference image id already exists: {identifier}")
            normalized_path = str(Path(path))
            if any(item.path == normalized_path and item.character_id == character_id for item in self._reference_images.values()):
                raise KnowledgeBaseDuplicateError(f"Duplicate reference image: {normalized_path}")
            self._next_reference_image_id = max(self._next_reference_image_id, identifier + 1)
            record = self.builder.build_reference_image_record(
                character_id=character_id,
                image_id=identifier,
                path=normalized_path,
                quality_score=quality_score,
                pose_type=pose_type,
                expression=expression,
                outfit=outfit,
                source=source,
                approved=approved,
                embedding_id=embedding_id,
                hash_id=hash_id,
                metadata=metadata,
            )
            self._reference_images[identifier] = record
            character.reference_images.append(record)
            character.updated_at = datetime.now(timezone.utc)
            self._recalculate_dataset_counts(character.dataset_id)
            return self._clone(record)

    def add_training_sample(
        self,
        *,
        character_id: int,
        image_id: int,
        approved: bool,
        reviewed_by: str | None = None,
        reviewed_at: datetime | None = None,
        confidence: float = 0.0,
        source: str | None = None,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
        lora_metadata: dict[str, Any] | None = None,
        sample_id: int | None = None,
    ) -> KnowledgeBaseTrainingSample:
        with self._lock:
            character = self._characters.get(character_id)
            if character is None:
                raise KnowledgeBaseNotFoundError(f"Character not found: {character_id}")
            identifier = sample_id or self._next_training_sample_id
            if identifier in self._training_samples:
                raise KnowledgeBaseDuplicateError(f"Training sample id already exists: {identifier}")
            self._next_training_sample_id = max(self._next_training_sample_id, identifier + 1)
            record = self.builder.build_training_sample_record(
                character_id=character_id,
                sample_id=identifier,
                image_id=image_id,
                approved=approved,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                confidence=confidence,
                source=source,
                weight=weight,
                metadata=metadata,
                lora_metadata=lora_metadata,
            )
            self._training_samples[identifier] = record
            character.approved_examples.append(record)
            character.confidence_score = self._adjust_confidence(character.confidence_score, record)
            character.updated_at = datetime.now(timezone.utc)
            self._recalculate_dataset_counts(character.dataset_id)
            return self._clone(record)

    def add_approved_review_sample(
        self,
        review_item: ReviewItem,
        *,
        dataset_id: int,
        character_id: int,
        weight: float = 1.0,
        lora_metadata: dict[str, Any] | None = None,
    ) -> KnowledgeBaseTrainingSample:
        reviewed_at = review_item.timestamp if review_item.status is ReviewStatus.APPROVED else datetime.now(timezone.utc)
        proposed = review_item.proposed_value if isinstance(review_item.proposed_value, dict) else {}
        return self.add_training_sample(
            character_id=character_id,
            image_id=review_item.image_id,
            approved=review_item.status is ReviewStatus.APPROVED,
            reviewed_by=review_item.reviewer,
            reviewed_at=reviewed_at,
            confidence=float(proposed.get("confidence", review_item.confidence or 0.0)),
            source="review",
            weight=weight,
            metadata={"review_id": review_item.review_id, "decision_reason": review_item.decision_reason},
            lora_metadata=lora_metadata or {
                "series": proposed.get("series_name"),
                "character": proposed.get("character_name"),
            },
        )

    def promote_trusted_sample(self, sample_id: int) -> KnowledgeBaseTrainingSample:
        with self._lock:
            sample = self._training_samples.get(sample_id)
            if sample is None:
                raise KnowledgeBaseNotFoundError(f"Training sample not found: {sample_id}")
            sample.approved = True
            sample.weight = max(sample.weight, 1.5)
            sample.reviewed_at = sample.reviewed_at or datetime.now(timezone.utc)
            return self._clone(sample)

    def reject_training_sample(self, sample_id: int) -> KnowledgeBaseTrainingSample:
        with self._lock:
            sample = self._training_samples.get(sample_id)
            if sample is None:
                raise KnowledgeBaseNotFoundError(f"Training sample not found: {sample_id}")
            sample.approved = False
            sample.weight = min(sample.weight, 0.25)
            sample.reviewed_at = sample.reviewed_at or datetime.now(timezone.utc)
            return self._clone(sample)

    # ------------------------------------------------------------------
    # Finders and search
    # ------------------------------------------------------------------
    def find_series(self, series_id: int) -> KnowledgeBaseSeries | None:
        record = self._series.get(series_id)
        return self._clone(record) if record is not None else None

    def find_character(self, character_id: int) -> KnowledgeBaseCharacter | None:
        record = self._characters.get(character_id)
        return self._clone(record) if record is not None else None

    def find_reference_image(self, image_id: int) -> KnowledgeBaseReferenceImage | None:
        record = self._reference_images.get(image_id)
        return self._clone(record) if record is not None else None

    def find_training_sample(self, sample_id: int) -> KnowledgeBaseTrainingSample | None:
        record = self._training_samples.get(sample_id)
        return self._clone(record) if record is not None else None

    def search_characters(self, query: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._search_records(query, dataset_id=dataset_id, limit=limit, kinds={KnowledgeBaseRecordKind.CHARACTER})

    def search_series(self, query: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._search_records(query, dataset_id=dataset_id, limit=limit, kinds={KnowledgeBaseRecordKind.SERIES})

    def search_datasets(self, query: str, *, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._search_records(query, dataset_id=None, limit=limit, kinds={KnowledgeBaseRecordKind.DATASET})

    def search_tags(self, query: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._search_records(query, dataset_id=dataset_id, limit=limit, kinds={KnowledgeBaseRecordKind.CHARACTER, KnowledgeBaseRecordKind.SERIES})

    def lookup_by_alias(self, alias: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._search_records(alias, dataset_id=dataset_id, limit=limit, kinds={KnowledgeBaseRecordKind.CHARACTER, KnowledgeBaseRecordKind.SERIES}, exact_fields={"aliases"})

    def lookup_by_character(self, character: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self.search_characters(character, dataset_id=dataset_id, limit=limit)

    def lookup_by_series(self, series: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self.search_series(series, dataset_id=dataset_id, limit=limit)

    def lookup_by_localized_name(self, name: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._search_records(name, dataset_id=dataset_id, limit=limit, kinds={KnowledgeBaseRecordKind.CHARACTER, KnowledgeBaseRecordKind.SERIES}, exact_fields={"localized_names", "localized_titles"})

    def lookup_by_romaji(self, name: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._search_records(name, dataset_id=dataset_id, limit=limit, kinds={KnowledgeBaseRecordKind.CHARACTER, KnowledgeBaseRecordKind.SERIES}, exact_fields={"romaji"})

    def lookup_by_canonical_id(self, identifier: int, *, dataset_id: int | None = None) -> list[KnowledgeBaseCandidate]:
        candidates: list[KnowledgeBaseCandidate] = []
        if identifier in self._characters:
            candidates.append(self._candidate_from_character(self._characters[identifier], score=1.0, matched_field="canonical_id"))
        if identifier in self._series:
            candidates.append(self._candidate_from_series(self._series[identifier], score=1.0, matched_field="canonical_id"))
        if dataset_id is not None:
            candidates = [item for item in candidates if item.dataset_id == dataset_id]
        return self._sort_candidates(candidates)

    def lookup_candidates(self, query: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        cache_key = self._search_cache_key(query, dataset_id, limit)
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return [self._clone(item) for item in cached[:limit]]

        candidates = self._search_records(
            query,
            dataset_id=dataset_id,
            limit=limit,
            kinds={KnowledgeBaseRecordKind.CHARACTER, KnowledgeBaseRecordKind.SERIES, KnowledgeBaseRecordKind.DATASET},
        )
        self._search_cache[cache_key] = [self._clone(item) for item in candidates]
        return candidates

    # ------------------------------------------------------------------
    # Import/export
    # ------------------------------------------------------------------
    def export_dataset(self, dataset_id: int, *, format: KnowledgeBaseImportFormat | str = KnowledgeBaseImportFormat.JSON) -> str | dict[str, Any]:
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise KnowledgeBaseNotFoundError(f"Dataset not found: {dataset_id}")
        bundle = self.builder.build_export_bundle(
            dataset=dataset,
            series=[item for item in self._series.values() if item.dataset_id == dataset_id],
            characters=[item for item in self._characters.values() if item.dataset_id == dataset_id],
            reference_images=[reference for character in self._characters.values() if character.dataset_id == dataset_id for reference in character.reference_images],
            training_samples=[sample for character in self._characters.values() if character.dataset_id == dataset_id for sample in character.approved_examples],
        )
        return self.builder.serialize_bundle(bundle, format=format)

    def import_dataset(
        self,
        data: str | dict[str, Any],
        *,
        format: KnowledgeBaseImportFormat | str = KnowledgeBaseImportFormat.JSON,
        merge: bool = False,
    ) -> KnowledgeBaseDataset:
        bundle = self.builder.deserialize_bundle(data, format=format)
        return self.import_bundle(bundle, merge=merge)

    def import_bundle(self, bundle: dict[str, Any], *, merge: bool = False) -> KnowledgeBaseDataset:
        with self._lock:
            dataset_payload = dict(bundle.get("dataset", {}))
            if not dataset_payload:
                raise KnowledgeBaseImportError("Missing dataset payload in import bundle")
            dataset_id = int(dataset_payload.get("dataset_id") or self._next_dataset_id)
            existing = self._datasets.get(dataset_id)
            if existing is None:
                dataset = self.builder.build_dataset_record(
                    dataset_id=dataset_id,
                    name=str(dataset_payload.get("name", "")).strip(),
                    description=str(dataset_payload.get("description", "")),
                    version=str(dataset_payload.get("version", "1.0")),
                    status=KnowledgeBaseDatasetStatus(str(dataset_payload.get("status", KnowledgeBaseDatasetStatus.ACTIVE.value))),
                    tags=list(dataset_payload.get("tags", [])),
                    notes=str(dataset_payload.get("notes", "")),
                )
                self._datasets[dataset_id] = dataset
                self._next_dataset_id = max(self._next_dataset_id, dataset_id + 1)
            elif merge:
                dataset = self._datasets[dataset_id]
                dataset.name = str(dataset_payload.get("name", dataset.name)).strip() or dataset.name
                dataset.description = str(dataset_payload.get("description", dataset.description))
                dataset.version = str(dataset_payload.get("version", dataset.version))
                status_value = str(dataset_payload.get("status", dataset.status.value))
                dataset.status = KnowledgeBaseDatasetStatus(status_value)
                dataset.tags = self._dedupe_text(dataset.tags + list(dataset_payload.get("tags", [])))
                dataset.notes = str(dataset_payload.get("notes", dataset.notes))
                dataset.updated_at = datetime.now(timezone.utc)
            else:
                raise KnowledgeBaseDuplicateError(f"Dataset id already exists: {dataset_id}")

            for series_payload in bundle.get("series", []):
                self._import_series(dataset_id=dataset_id, payload=dict(series_payload), merge=merge)
            for character_payload in bundle.get("characters", []):
                self._import_character(dataset_id=dataset_id, payload=dict(character_payload), merge=merge)
            for reference_payload in bundle.get("reference_images", []):
                self._import_reference_image(dataset_id=dataset_id, payload=dict(reference_payload), merge=merge)
            for sample_payload in bundle.get("training_samples", []):
                self._import_training_sample(dataset_id=dataset_id, payload=dict(sample_payload), merge=merge)

            self._recalculate_dataset_counts(dataset_id)
            self._search_cache.clear()
            return self._clone(self._datasets[dataset_id])

    # ------------------------------------------------------------------
    # Validation and statistics
    # ------------------------------------------------------------------
    def validate(self, dataset_id: int | None = None) -> KnowledgeBaseValidationReport:
        datasets = [self._datasets[dataset_id]] if dataset_id is not None and dataset_id in self._datasets else list(self._datasets.values())
        issues = []
        duplicate_ids = 0
        duplicate_aliases = 0
        missing_series = 0
        broken_references = 0
        duplicate_reference_images = 0
        orphan_characters = 0
        orphan_series = 0
        invalid_datasets = 0
        empty_datasets = 0

        seen_aliases: dict[str, int] = {}
        seen_reference_paths: set[tuple[int, str]] = set()

        for dataset in datasets:
            if not dataset.name.strip():
                invalid_datasets += 1
                issues.append(self.builder.build_validation_issue(severity="error", code="invalid_dataset", message="Dataset name cannot be empty."))
            series = [item for item in self._series.values() if item.dataset_id == dataset.dataset_id]
            characters = [item for item in self._characters.values() if item.dataset_id == dataset.dataset_id]
            reference_images = [reference for character in characters for reference in character.reference_images]
            if not series and not characters:
                empty_datasets += 1

            for series_record in series:
                if series_record.parent_series_id is not None and series_record.parent_series_id not in self._series:
                    broken_references += 1
                for alias in self._alias_values_for_series(series_record):
                    key = self.builder.normalize_text(alias)
                    if key and key in seen_aliases:
                        duplicate_aliases += 1
                    if key:
                        seen_aliases[key] = series_record.canonical_id

            for character in characters:
                if character.series_id is None:
                    orphan_characters += 1
                elif character.series_id not in self._series:
                    missing_series += 1
                    broken_references += 1
                if not character.reference_images:
                    orphan_series += 1 if character.series_id is None else 0
                for alias in self._alias_values_for_character(character):
                    key = self.builder.normalize_text(alias)
                    if key and key in seen_aliases:
                        duplicate_aliases += 1
                    if key:
                        seen_aliases[key] = character.canonical_id
                for ref in character.reference_images:
                    ref_key = (character.canonical_id, ref.path)
                    if ref_key in seen_reference_paths:
                        duplicate_reference_images += 1
                    else:
                        seen_reference_paths.add(ref_key)
                    if ref.image_id not in self._reference_images:
                        broken_references += 1
                for sample in character.approved_examples:
                    if sample.sample_id not in self._training_samples:
                        broken_references += 1

            if not characters:
                orphan_series += len(series)

        report = self.builder.build_validation_report(
            issues=issues,
            duplicate_ids=duplicate_ids,
            duplicate_aliases=duplicate_aliases,
            missing_series=missing_series,
            broken_references=broken_references,
            duplicate_reference_images=duplicate_reference_images,
            orphan_characters=orphan_characters,
            orphan_series=orphan_series,
            invalid_datasets=invalid_datasets,
            empty_datasets=empty_datasets,
        )
        return report

    def counts(self, dataset_id: int | None = None) -> dict[str, int]:
        datasets = [self._datasets[dataset_id]] if dataset_id is not None and dataset_id in self._datasets else list(self._datasets.values())
        series = [item for item in self._series.values() if dataset_id is None or item.dataset_id == dataset_id]
        characters = [item for item in self._characters.values() if dataset_id is None or item.dataset_id == dataset_id]
        reference_images = [reference for character in characters for reference in character.reference_images]
        training_samples = [sample for character in characters for sample in character.approved_examples]
        alias_count = sum(len(self._alias_values_for_series(item)) for item in series) + sum(len(self._alias_values_for_character(item)) for item in characters)
        return {
            "datasets": len(datasets),
            "characters": len(characters),
            "series": len(series),
            "aliases": alias_count,
            "training_samples": len(training_samples),
            "reference_images": len(reference_images),
        }

    def merge_datasets(self, target_dataset_id: int, source_dataset_id: int) -> KnowledgeBaseDataset:
        with self._lock:
            target = self._datasets.get(target_dataset_id)
            source = self._datasets.get(source_dataset_id)
            if target is None or source is None:
                raise KnowledgeBaseNotFoundError("Target or source dataset not found")
            for series in [item for item in self._series.values() if item.dataset_id == source_dataset_id]:
                series.dataset_id = target_dataset_id
            for character in [item for item in self._characters.values() if item.dataset_id == source_dataset_id]:
                character.dataset_id = target_dataset_id
            for reference in [item for item in self._reference_images.values() if item.dataset_id == source_dataset_id]:
                reference.dataset_id = target_dataset_id
            for sample in [item for item in self._training_samples.values() if item.dataset_id == source_dataset_id]:
                sample.dataset_id = target_dataset_id
            del self._datasets[source_dataset_id]
            target.updated_at = datetime.now(timezone.utc)
            self._recalculate_dataset_counts(target_dataset_id)
            self._search_cache.clear()
            return self._clone(target)

    # ------------------------------------------------------------------
    # Internal import helpers
    # ------------------------------------------------------------------
    def _import_series(self, *, dataset_id: int, payload: dict[str, Any], merge: bool) -> KnowledgeBaseSeries:
        identifier = int(payload.get("canonical_id") or self._next_series_id)
        existing = self._series.get(identifier)
        if existing is None:
            record = self.builder.build_series_record(
                dataset_id=dataset_id,
                canonical_id=identifier,
                title=str(payload.get("title", "")).strip(),
                aliases=list(payload.get("aliases", [])),
                localized_titles=list(payload.get("localized_titles", [])),
                description=str(payload.get("description", "")),
                parent_series_id=payload.get("parent_series_id"),
                related_series_ids=list(payload.get("related_series_ids", [])),
                character_ids=list(payload.get("character_ids", [])),
                tags=list(payload.get("tags", [])),
                notes=str(payload.get("notes", "")),
            )
            self._series[identifier] = record
            self._next_series_id = max(self._next_series_id, identifier + 1)
            return self._clone(record)
        if not merge:
            raise KnowledgeBaseDuplicateError(f"Series id already exists: {identifier}")
        existing.dataset_id = dataset_id
        existing.title = str(payload.get("title", existing.title)).strip() or existing.title
        existing.aliases = self._dedupe_text(existing.aliases + list(payload.get("aliases", [])))
        existing.localized_titles = self._dedupe_text(existing.localized_titles + list(payload.get("localized_titles", [])))
        existing.description = str(payload.get("description", existing.description))
        existing.parent_series_id = payload.get("parent_series_id", existing.parent_series_id)
        existing.related_series_ids = self._dedupe_ints(existing.related_series_ids + list(payload.get("related_series_ids", [])))
        existing.character_ids = self._dedupe_ints(existing.character_ids + list(payload.get("character_ids", [])))
        existing.tags = self._dedupe_text(existing.tags + list(payload.get("tags", [])))
        existing.notes = str(payload.get("notes", existing.notes))
        existing.updated_at = datetime.now(timezone.utc)
        return self._clone(existing)

    def _import_character(self, *, dataset_id: int, payload: dict[str, Any], merge: bool) -> KnowledgeBaseCharacter:
        identifier = int(payload.get("canonical_id") or self._next_character_id)
        existing = self._characters.get(identifier)
        if existing is None:
            record = self.builder.build_character_record(
                dataset_id=dataset_id,
                canonical_id=identifier,
                series_id=payload.get("series_id"),
                canonical_name=str(payload.get("canonical_name", "")).strip(),
                aliases=list(payload.get("aliases", [])),
                localized_names=list(payload.get("localized_names", [])),
                romaji=payload.get("romaji"),
                japanese=payload.get("japanese"),
                english=payload.get("english"),
                gender=payload.get("gender"),
                description=str(payload.get("description", "")),
                tags=list(payload.get("tags", [])),
                notes=str(payload.get("notes", "")),
                confidence_score=float(payload.get("confidence_score", 0.0)),
                training_priority=float(payload.get("training_priority", 1.0)),
            )
            self._characters[identifier] = record
            self._next_character_id = max(self._next_character_id, identifier + 1)
            if record.series_id is not None and record.series_id in self._series:
                self._series[record.series_id].character_ids = self._dedupe_ints(self._series[record.series_id].character_ids + [identifier])
            return self._clone(record)
        if not merge:
            raise KnowledgeBaseDuplicateError(f"Character id already exists: {identifier}")
        existing.dataset_id = dataset_id
        existing.series_id = payload.get("series_id", existing.series_id)
        existing.canonical_name = str(payload.get("canonical_name", existing.canonical_name)).strip() or existing.canonical_name
        existing.aliases = self._dedupe_text(existing.aliases + list(payload.get("aliases", [])))
        existing.localized_names = self._dedupe_text(existing.localized_names + list(payload.get("localized_names", [])))
        existing.romaji = payload.get("romaji", existing.romaji)
        existing.japanese = payload.get("japanese", existing.japanese)
        existing.english = payload.get("english", existing.english)
        existing.gender = payload.get("gender", existing.gender)
        existing.description = str(payload.get("description", existing.description))
        existing.tags = self._dedupe_text(existing.tags + list(payload.get("tags", [])))
        existing.notes = str(payload.get("notes", existing.notes))
        existing.confidence_score = float(payload.get("confidence_score", existing.confidence_score))
        existing.training_priority = float(payload.get("training_priority", existing.training_priority))
        existing.updated_at = datetime.now(timezone.utc)
        if existing.series_id is not None and existing.series_id in self._series:
            self._series[existing.series_id].character_ids = self._dedupe_ints(self._series[existing.series_id].character_ids + [identifier])
        return self._clone(existing)

    def _import_reference_image(self, *, dataset_id: int, payload: dict[str, Any], merge: bool) -> KnowledgeBaseReferenceImage:
        image_id = int(payload.get("image_id") or self._next_reference_image_id)
        character_id = int(payload.get("character_id", 0))
        character = self._characters.get(character_id)
        if character is None:
            raise KnowledgeBaseNotFoundError(f"Character not found for reference image: {character_id}")
        existing = self._reference_images.get(image_id)
        if existing is None:
            record = self.builder.build_reference_image_record(
                character_id=character_id,
                image_id=image_id,
                path=str(payload.get("path", "")),
                quality_score=float(payload.get("quality_score", 0.0)),
                pose_type=payload.get("pose_type"),
                expression=payload.get("expression"),
                outfit=payload.get("outfit"),
                source=payload.get("source"),
                approved=bool(payload.get("approved", True)),
                embedding_id=payload.get("embedding_id"),
                hash_id=payload.get("hash_id"),
                metadata=dict(payload.get("metadata", {})),
            )
            self._reference_images[image_id] = record
            character.reference_images.append(record)
            self._next_reference_image_id = max(self._next_reference_image_id, image_id + 1)
            self._recalculate_dataset_counts(character.dataset_id)
            return self._clone(record)
        if not merge:
            raise KnowledgeBaseDuplicateError(f"Reference image id already exists: {image_id}")
        existing.character_id = character_id
        existing.path = str(payload.get("path", existing.path))
        existing.quality_score = float(payload.get("quality_score", existing.quality_score))
        existing.pose_type = payload.get("pose_type", existing.pose_type)
        existing.expression = payload.get("expression", existing.expression)
        existing.outfit = payload.get("outfit", existing.outfit)
        existing.source = payload.get("source", existing.source)
        existing.approved = bool(payload.get("approved", existing.approved))
        existing.embedding_id = payload.get("embedding_id", existing.embedding_id)
        existing.hash_id = payload.get("hash_id", existing.hash_id)
        existing.metadata = dict(payload.get("metadata", existing.metadata))
        if existing not in character.reference_images:
            character.reference_images.append(existing)
        self._recalculate_dataset_counts(character.dataset_id)
        return self._clone(existing)

    def _import_training_sample(self, *, dataset_id: int, payload: dict[str, Any], merge: bool) -> KnowledgeBaseTrainingSample:
        sample_id = int(payload.get("sample_id") or self._next_training_sample_id)
        character_id = int(payload.get("character_id", 0))
        character = self._characters.get(character_id)
        if character is None:
            raise KnowledgeBaseNotFoundError(f"Character not found for training sample: {character_id}")
        existing = self._training_samples.get(sample_id)
        if existing is None:
            record = self.builder.build_training_sample_record(
                character_id=character_id,
                sample_id=sample_id,
                image_id=int(payload.get("image_id", 0)),
                approved=bool(payload.get("approved", False)),
                reviewed_by=payload.get("reviewed_by"),
                reviewed_at=self._parse_datetime(payload.get("reviewed_at")),
                confidence=float(payload.get("confidence", 0.0)),
                source=payload.get("source"),
                weight=float(payload.get("weight", 1.0)),
                metadata=dict(payload.get("metadata", {})),
                lora_metadata=dict(payload.get("lora_metadata", {})),
            )
            self._training_samples[sample_id] = record
            character.approved_examples.append(record)
            self._next_training_sample_id = max(self._next_training_sample_id, sample_id + 1)
            self._recalculate_dataset_counts(character.dataset_id)
            return self._clone(record)
        if not merge:
            raise KnowledgeBaseDuplicateError(f"Training sample id already exists: {sample_id}")
        existing.character_id = character_id
        existing.approved = bool(payload.get("approved", existing.approved))
        existing.reviewed_by = payload.get("reviewed_by", existing.reviewed_by)
        existing.reviewed_at = self._parse_datetime(payload.get("reviewed_at")) or existing.reviewed_at
        existing.confidence = float(payload.get("confidence", existing.confidence))
        existing.source = payload.get("source", existing.source)
        existing.weight = float(payload.get("weight", existing.weight))
        existing.metadata = dict(payload.get("metadata", existing.metadata))
        existing.lora_metadata = dict(payload.get("lora_metadata", existing.lora_metadata))
        if existing not in character.approved_examples:
            character.approved_examples.append(existing)
        self._recalculate_dataset_counts(character.dataset_id)
        return self._clone(existing)

    # ------------------------------------------------------------------
    # Search helpers
    # ------------------------------------------------------------------
    def _search_records(
        self,
        query: str,
        *,
        dataset_id: int | None,
        limit: int,
        kinds: set[KnowledgeBaseRecordKind],
        exact_fields: set[str] | None = None,
    ) -> list[KnowledgeBaseCandidate]:
        exact_fields = exact_fields or set()
        normalized_query = self.builder.normalize_text(query)
        if not normalized_query:
            return []

        candidates: list[KnowledgeBaseCandidate] = []
        if KnowledgeBaseRecordKind.DATASET in kinds:
            for dataset in self._datasets.values():
                if dataset_id is not None and dataset.dataset_id != dataset_id:
                    continue
                candidates.extend(self._score_dataset(dataset, normalized_query, exact_fields))
        if KnowledgeBaseRecordKind.SERIES in kinds:
            for series in self._series.values():
                if dataset_id is not None and series.dataset_id != dataset_id:
                    continue
                candidates.extend(self._score_series(series, normalized_query, exact_fields))
        if KnowledgeBaseRecordKind.CHARACTER in kinds:
            for character in self._characters.values():
                if dataset_id is not None and character.dataset_id != dataset_id:
                    continue
                candidates.extend(self._score_character(character, normalized_query, exact_fields))
        return self._sort_candidates(candidates)[:limit]

    def _score_dataset(self, dataset: KnowledgeBaseDataset, query: str, exact_fields: set[str]) -> list[KnowledgeBaseCandidate]:
        fields = {
            "name": [dataset.name],
            "description": [dataset.description],
            "version": [dataset.version],
            "status": [dataset.status.value],
            "notes": [dataset.notes],
            "tags": dataset.tags,
        }
        return self._score_record(
            kind=KnowledgeBaseRecordKind.DATASET,
            record_id=dataset.dataset_id,
            dataset_id=dataset.dataset_id,
            name=dataset.name,
            query=query,
            fields=fields,
            exact_fields=exact_fields,
            payload={"status": dataset.status.value, "version": dataset.version, "tags": list(dataset.tags)},
        )

    def _score_series(self, series: KnowledgeBaseSeries, query: str, exact_fields: set[str]) -> list[KnowledgeBaseCandidate]:
        fields = {
            "title": [series.title],
            "aliases": series.aliases,
            "localized_titles": series.localized_titles,
            "description": [series.description],
            "tags": series.tags,
            "notes": [series.notes],
        }
        return self._score_record(
            kind=KnowledgeBaseRecordKind.SERIES,
            record_id=series.canonical_id,
            dataset_id=series.dataset_id,
            name=series.title,
            query=query,
            fields=fields,
            exact_fields=exact_fields,
            payload={"parent_series_id": series.parent_series_id, "tags": list(series.tags)},
        )

    def _score_character(self, character: KnowledgeBaseCharacter, query: str, exact_fields: set[str]) -> list[KnowledgeBaseCandidate]:
        fields = {
            "canonical_name": [character.canonical_name],
            "aliases": character.aliases,
            "localized_names": character.localized_names,
            "romaji": [character.romaji or ""],
            "japanese": [character.japanese or ""],
            "english": [character.english or ""],
            "gender": [character.gender or ""],
            "description": [character.description],
            "tags": character.tags,
            "notes": [character.notes],
        }
        series_name = self._series.get(character.series_id).title if character.series_id in self._series else None
        return self._score_record(
            kind=KnowledgeBaseRecordKind.CHARACTER,
            record_id=character.canonical_id,
            dataset_id=character.dataset_id,
            name=character.canonical_name,
            query=query,
            fields=fields,
            exact_fields=exact_fields,
            series_id=character.series_id,
            series_name=series_name,
            payload={"series_id": character.series_id, "tags": list(character.tags), "confidence_score": character.confidence_score},
        )

    def _score_record(
        self,
        *,
        kind: KnowledgeBaseRecordKind,
        record_id: int,
        dataset_id: int,
        name: str,
        query: str,
        fields: dict[str, list[str]],
        exact_fields: set[str],
        series_id: int | None = None,
        series_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> list[KnowledgeBaseCandidate]:
        candidates: list[KnowledgeBaseCandidate] = []
        for field_name, values in fields.items():
            for value in values:
                normalized = self.builder.normalize_text(value)
                if not normalized:
                    continue
                if query == normalized:
                    score = 1.0
                elif field_name in exact_fields and query in normalized:
                    score = 0.96
                else:
                    score = SequenceMatcher(None, query, normalized).ratio()
                    if query in normalized or normalized in query:
                        score = max(score, 0.9)
                if score >= 0.65:
                    query_tokens = self.builder.tokenize_text(query)
                    normalized_tokens = self.builder.tokenize_text(normalized)
                    if query_tokens and normalized_tokens:
                        overlap = sum(
                            1
                            for token in query_tokens
                            if any(token in candidate or candidate in token for candidate in normalized_tokens)
                        ) / len(query_tokens)
                        if overlap >= 0.5:
                            score = max(score, 0.8)
                    candidates.append(
                        self.builder.build_candidate(
                            kind=kind,
                            record_id=record_id,
                            dataset_id=dataset_id,
                            name=name,
                            score=score,
                            matched_field=field_name,
                            series_id=series_id,
                            series_name=series_name,
                            tags=payload.get("tags", []) if payload else [],
                            payload=dict(payload or {}),
                            fuzzy=score < 1.0,
                        )
                    )
        if not candidates and query == self.builder.normalize_text(name):
            candidates.append(
                self.builder.build_candidate(
                    kind=kind,
                    record_id=record_id,
                    dataset_id=dataset_id,
                    name=name,
                    score=1.0,
                    matched_field="canonical_name" if kind is KnowledgeBaseRecordKind.CHARACTER else ("title" if kind is KnowledgeBaseRecordKind.SERIES else "name"),
                    series_id=series_id,
                    series_name=series_name,
                    tags=payload.get("tags", []) if payload else [],
                    payload=dict(payload or {}),
                )
            )
        return candidates

    def _candidate_from_character(self, character: KnowledgeBaseCharacter, *, score: float, matched_field: str) -> KnowledgeBaseCandidate:
        series = self._series.get(character.series_id) if character.series_id is not None else None
        return self.builder.build_candidate(
            kind=KnowledgeBaseRecordKind.CHARACTER,
            record_id=character.canonical_id,
            dataset_id=character.dataset_id,
            name=character.canonical_name,
            score=score,
            matched_field=matched_field,
            series_id=character.series_id,
            series_name=series.title if series is not None else None,
            tags=list(character.tags),
            payload={"series_id": character.series_id, "tags": list(character.tags)},
        )

    def _candidate_from_series(self, series: KnowledgeBaseSeries, *, score: float, matched_field: str) -> KnowledgeBaseCandidate:
        return self.builder.build_candidate(
            kind=KnowledgeBaseRecordKind.SERIES,
            record_id=series.canonical_id,
            dataset_id=series.dataset_id,
            name=series.title,
            score=score,
            matched_field=matched_field,
            tags=list(series.tags),
            payload={"parent_series_id": series.parent_series_id, "tags": list(series.tags)},
        )

    def _sort_candidates(self, candidates: list[KnowledgeBaseCandidate]) -> list[KnowledgeBaseCandidate]:
        priority = {
            KnowledgeBaseRecordKind.CHARACTER: 0,
            KnowledgeBaseRecordKind.SERIES: 1,
            KnowledgeBaseRecordKind.DATASET: 2,
        }
        return sorted(
            candidates,
            key=lambda item: (-item.score, priority.get(item.kind, 99), item.name.casefold(), item.record_id),
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _require_dataset(self, dataset_id: int) -> None:
        if dataset_id not in self._datasets:
            raise KnowledgeBaseNotFoundError(f"Dataset not found: {dataset_id}")

    def _recalculate_dataset_counts(self, dataset_id: int) -> None:
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            return
        series = [item for item in self._series.values() if item.dataset_id == dataset_id]
        characters = [item for item in self._characters.values() if item.dataset_id == dataset_id]
        reference_images = [reference for character in characters for reference in character.reference_images]
        training_samples = [sample for character in characters for sample in character.approved_examples]
        dataset.series_count = len(series)
        dataset.character_count = len(characters)
        dataset.reference_image_count = len(reference_images)
        dataset.image_count = len(reference_images)
        dataset.training_sample_count = len(training_samples)
        dataset.alias_count = sum(len(self._alias_values_for_series(item)) for item in series) + sum(len(self._alias_values_for_character(item)) for item in characters)
        dataset.updated_at = datetime.now(timezone.utc)

    def _alias_values_for_series(self, series: KnowledgeBaseSeries) -> list[str]:
        values = [series.title]
        values.extend(series.aliases)
        values.extend(series.localized_titles)
        return [item for item in values if str(item).strip()]

    def _alias_values_for_character(self, character: KnowledgeBaseCharacter) -> list[str]:
        values = [character.canonical_name]
        values.extend(character.aliases)
        values.extend(character.localized_names)
        values.extend([character.romaji or "", character.japanese or "", character.english or ""])
        return [item for item in values if str(item).strip()]

    def _adjust_confidence(self, current: float, sample: KnowledgeBaseTrainingSample) -> float:
        delta = 0.05 if sample.approved else -0.05
        delta *= max(0.2, min(2.0, sample.weight))
        return round(max(0.0, min(1.0, current + delta)), 4)

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _search_cache_key(self, query: str, dataset_id: int | None, limit: int) -> str:
        return f"{dataset_id or '*'}|{limit}|{self.builder.normalize_text(query)}"

    @staticmethod
    def _dedupe_text(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = str(value).strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(str(value).strip())
        return result

    @staticmethod
    def _dedupe_ints(values: list[int]) -> list[int]:
        seen: set[int] = set()
        result: list[int] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(int(value))
        return result

    def _clone(self, value: Any) -> Any:
        return deepcopy(value)
