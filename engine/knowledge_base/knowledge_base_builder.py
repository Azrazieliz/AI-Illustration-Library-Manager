from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from enum import Enum
from typing import Any

from engine.knowledge_base.knowledge_base_exceptions import KnowledgeBaseImportError
from engine.knowledge_base.knowledge_base_models import (
    KnowledgeBaseCandidate,
    KnowledgeBaseCharacter,
    KnowledgeBaseDataset,
    KnowledgeBaseDatasetStatus,
    KnowledgeBaseImportFormat,
    KnowledgeBaseOperationResult,
    KnowledgeBaseRecordKind,
    KnowledgeBaseReferenceImage,
    KnowledgeBaseRelationship,
    KnowledgeBaseSeries,
    KnowledgeBaseTaskType,
    KnowledgeBaseTrainingSample,
    KnowledgeBaseValidationIssue,
    KnowledgeBaseValidationReport,
)


class KnowledgeBaseBuilder:
    """Builder and serializer for trusted knowledge-base records."""

    def normalize_text(self, value: Any) -> str:
        text = "" if value is None else str(value)
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
        text = re.sub(r"\s+", " ", text).strip().casefold()
        return text

    def tokenize_text(self, value: Any) -> list[str]:
        normalized = self.normalize_text(value)
        return [item for item in normalized.split(" ") if item]

    def build_dataset_record(
        self,
        *,
        dataset_id: int,
        name: str,
        description: str = "",
        version: str = "1.0",
        status: KnowledgeBaseDatasetStatus = KnowledgeBaseDatasetStatus.ACTIVE,
        tags: list[str] | None = None,
        notes: str = "",
    ) -> KnowledgeBaseDataset:
        return KnowledgeBaseDataset(
            dataset_id=dataset_id,
            name=name.strip(),
            description=description,
            version=version,
            status=status,
            tags=list(tags or []),
            notes=notes,
        )

    def build_series_record(
        self,
        *,
        dataset_id: int,
        canonical_id: int,
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
        return KnowledgeBaseSeries(
            canonical_id=canonical_id,
            dataset_id=dataset_id,
            title=title.strip(),
            aliases=list(aliases or []),
            localized_titles=list(localized_titles or []),
            description=description,
            parent_series_id=parent_series_id,
            related_series_ids=list(related_series_ids or []),
            character_ids=list(character_ids or []),
            tags=list(tags or []),
            notes=notes,
        )

    def build_character_record(
        self,
        *,
        dataset_id: int,
        canonical_id: int,
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
        return KnowledgeBaseCharacter(
            canonical_id=canonical_id,
            dataset_id=dataset_id,
            series_id=series_id,
            canonical_name=canonical_name.strip(),
            aliases=list(aliases or []),
            localized_names=list(localized_names or []),
            romaji=romaji,
            japanese=japanese,
            english=english,
            gender=gender,
            description=description,
            tags=list(tags or []),
            notes=notes,
            confidence_score=confidence_score,
            training_priority=training_priority,
        )

    def build_reference_image_record(
        self,
        *,
        character_id: int,
        image_id: int,
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
        return KnowledgeBaseReferenceImage(
            image_id=image_id,
            character_id=character_id,
            path=str(path),
            quality_score=quality_score,
            pose_type=pose_type,
            expression=expression,
            outfit=outfit,
            source=source,
            approved=approved,
            embedding_id=embedding_id,
            hash_id=hash_id,
            metadata=dict(metadata or {}),
        )

    def build_training_sample_record(
        self,
        *,
        character_id: int,
        sample_id: int,
        image_id: int,
        approved: bool,
        reviewed_by: str | None = None,
        reviewed_at: datetime | None = None,
        confidence: float = 0.0,
        source: str | None = None,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
        lora_metadata: dict[str, Any] | None = None,
    ) -> KnowledgeBaseTrainingSample:
        return KnowledgeBaseTrainingSample(
            sample_id=sample_id,
            character_id=character_id,
            image_id=image_id,
            approved=approved,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            confidence=confidence,
            source=source,
            weight=weight,
            metadata=dict(metadata or {}),
            lora_metadata=dict(lora_metadata or {}),
        )

    def build_relationship_record(
        self,
        *,
        relation: str,
        target_kind: KnowledgeBaseRecordKind,
        target_id: int,
        confidence: float = 0.0,
        notes: str = "",
    ) -> KnowledgeBaseRelationship:
        return KnowledgeBaseRelationship(
            relation=relation,
            target_kind=target_kind,
            target_id=target_id,
            confidence=confidence,
            notes=notes,
        )

    def build_candidate(
        self,
        *,
        kind: KnowledgeBaseRecordKind,
        record_id: int,
        dataset_id: int,
        name: str,
        score: float,
        matched_field: str = "",
        series_id: int | None = None,
        series_name: str | None = None,
        tags: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        fuzzy: bool = False,
        unknown: bool = False,
    ) -> KnowledgeBaseCandidate:
        return KnowledgeBaseCandidate(
            kind=kind,
            record_id=record_id,
            dataset_id=dataset_id,
            name=name,
            score=round(max(0.0, min(1.0, score)), 4),
            matched_field=matched_field,
            series_id=series_id,
            series_name=series_name,
            tags=list(tags or []),
            payload=dict(payload or {}),
            fuzzy=fuzzy,
            unknown=unknown,
        )

    def build_validation_issue(self, *, severity: str, code: str, message: str) -> KnowledgeBaseValidationIssue:
        return KnowledgeBaseValidationIssue(severity=severity, code=code, message=message)

    def build_validation_report(
        self,
        *,
        issues: list[KnowledgeBaseValidationIssue],
        duplicate_ids: int,
        duplicate_aliases: int,
        missing_series: int,
        broken_references: int,
        duplicate_reference_images: int,
        orphan_characters: int,
        orphan_series: int,
        invalid_datasets: int,
        empty_datasets: int,
    ) -> KnowledgeBaseValidationReport:
        has_error = any(issue.severity.lower() == "error" for issue in issues) or any(
            [
                duplicate_ids,
                duplicate_aliases,
                missing_series,
                broken_references,
                duplicate_reference_images,
                orphan_characters,
                orphan_series,
                invalid_datasets,
                empty_datasets,
            ]
        )
        return KnowledgeBaseValidationReport(
            valid=not has_error,
            issues=list(issues),
            duplicate_ids=max(0, duplicate_ids),
            duplicate_aliases=max(0, duplicate_aliases),
            missing_series=max(0, missing_series),
            broken_references=max(0, broken_references),
            duplicate_reference_images=max(0, duplicate_reference_images),
            orphan_characters=max(0, orphan_characters),
            orphan_series=max(0, orphan_series),
            invalid_datasets=max(0, invalid_datasets),
            empty_datasets=max(0, empty_datasets),
        )

    def build_operation_result(
        self,
        *,
        action: KnowledgeBaseTaskType,
        success: bool,
        message: str = "",
        dataset_id: int | None = None,
        payload: dict[str, Any] | None = None,
        processed: int = 0,
        skipped: int = 0,
        failed: int = 0,
        progress: float = 0.0,
    ) -> KnowledgeBaseOperationResult:
        return KnowledgeBaseOperationResult(
            action=action,
            success=success,
            message=message,
            dataset_id=dataset_id,
            payload=dict(payload or {}),
            processed=processed,
            skipped=skipped,
            failed=failed,
            progress=round(max(0.0, min(1.0, progress)), 4),
        )

    def build_export_bundle(
        self,
        *,
        dataset: KnowledgeBaseDataset,
        series: list[KnowledgeBaseSeries],
        characters: list[KnowledgeBaseCharacter],
        reference_images: list[KnowledgeBaseReferenceImage],
        training_samples: list[KnowledgeBaseTrainingSample],
    ) -> dict[str, Any]:
        return {
            "dataset": self._record_to_dict(dataset),
            "series": [self._record_to_dict(item) for item in series],
            "characters": [self._record_to_dict(item) for item in characters],
            "reference_images": [self._record_to_dict(item) for item in reference_images],
            "training_samples": [self._record_to_dict(item) for item in training_samples],
            "format_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def serialize_bundle(self, bundle: dict[str, Any], *, format: KnowledgeBaseImportFormat | str) -> str | dict[str, Any]:
        format_value = format.value if isinstance(format, KnowledgeBaseImportFormat) else str(format).lower()
        if format_value in {KnowledgeBaseImportFormat.JSON.value, KnowledgeBaseImportFormat.YAML.value}:
            # YAML-ready architecture: the bundle is already YAML-compatible; JSON text keeps the implementation dependency-free.
            return json.dumps(bundle, ensure_ascii=False, indent=2, default=self._json_default)
        if format_value == KnowledgeBaseImportFormat.CSV.value:
            return self.bundle_to_csv(bundle)
        raise KnowledgeBaseImportError(f"Unsupported export format: {format_value}")

    def deserialize_bundle(self, data: str | dict[str, Any], *, format: KnowledgeBaseImportFormat | str) -> dict[str, Any]:
        format_value = format.value if isinstance(format, KnowledgeBaseImportFormat) else str(format).lower()
        if isinstance(data, dict):
            return data
        if format_value in {KnowledgeBaseImportFormat.JSON.value, KnowledgeBaseImportFormat.YAML.value}:
            return json.loads(data)
        if format_value == KnowledgeBaseImportFormat.CSV.value:
            return self.csv_to_bundle(data)
        raise KnowledgeBaseImportError(f"Unsupported import format: {format_value}")

    def bundle_to_csv(self, bundle: dict[str, Any]) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["record_type", "payload"])
        writer.writeheader()
        for record_type in ("dataset", "series", "characters", "reference_images", "training_samples"):
            rows = bundle.get(record_type, [])
            if record_type == "dataset":
                rows = [rows] if isinstance(rows, dict) else ([] if rows is None else list(rows))
            for row in rows:
                writer.writerow({"record_type": record_type, "payload": json.dumps(row, ensure_ascii=False, default=self._json_default)})
        return buffer.getvalue()

    def csv_to_bundle(self, data: str) -> dict[str, Any]:
        buffer = io.StringIO(data)
        reader = csv.DictReader(buffer)
        bundle: dict[str, Any] = {
            "dataset": {},
            "series": [],
            "characters": [],
            "reference_images": [],
            "training_samples": [],
        }
        for row in reader:
            record_type = (row.get("record_type") or "").strip()
            payload_text = row.get("payload") or "{}"
            payload = json.loads(payload_text)
            if record_type == "dataset":
                bundle["dataset"] = payload
            elif record_type in bundle:
                bundle[record_type].append(payload)
        return bundle

    def _record_to_dict(self, record: Any) -> dict[str, Any]:
        payload = asdict(record)
        return self._normalize_value(payload)

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {key: self._normalize_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._normalize_value(item) for item in value]
        if isinstance(value, set):
            return [self._normalize_value(item) for item in sorted(value, key=str)]
        return value

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, (datetime, Path)):
            return str(value)
        if isinstance(value, set):
            return sorted(value)
        return str(value)
