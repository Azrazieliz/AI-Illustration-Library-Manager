from __future__ import annotations

from pathlib import Path

from engine.dataset.dataset_models import DatasetEntry
from engine.export.export_exceptions import ExportFormatError
from engine.export.export_formats import ExportFormat, build_default_formats
from engine.export.export_models import ExportFilter, ExportFormatType, ExportRecord
from engine.repositories.export_repository import ExportRepository


class ExportBuilder:
    """Builds export records from canonical dataset entries."""

    def __init__(
        self,
        repository: ExportRepository | None = None,
        format_registry: dict[ExportFormatType, ExportFormat] | None = None,
    ) -> None:
        self.repository = repository or ExportRepository()
        self._format_registry = format_registry or build_default_formats()

    def matches_filter(self, entry: DatasetEntry, export_filter: ExportFilter | None) -> bool:
        if export_filter is None:
            return True

        if export_filter.image_ids and entry.image_id not in export_filter.image_ids:
            return False

        if entry.confidence_score < export_filter.min_confidence:
            return False

        if entry.quality_score < export_filter.min_quality:
            return False

        if entry.completeness_score < export_filter.min_completeness:
            return False

        tags = {
            str(item.get("name", "")).strip().lower()
            for item in entry.payload.get("tags", [])
            if isinstance(item, dict)
        }

        if export_filter.include_tags and tags.isdisjoint(export_filter.include_tags):
            return False

        if export_filter.exclude_tags and tags.intersection(export_filter.exclude_tags):
            return False

        return True

    def build_record(
        self,
        entry: DatasetEntry,
        *,
        format_type: ExportFormatType,
        semantic: dict | None = None,
    ) -> ExportRecord:
        format_handler = self._format_registry.get(format_type)
        if format_handler is None:
            raise ExportFormatError(f"Unsupported export format: {format_type.value}")

        tags = [
            str(item.get("name", "")).strip()
            for item in entry.payload.get("tags", [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]

        caption = _caption_from_entry(entry, semantic=semantic, tags=tags)

        base_payload = {
            "image": entry.payload.get("image", {}),
            "metadata": entry.payload.get("metadata", {}),
            "hashes": entry.payload.get("hashes", {}),
            "embedding": entry.payload.get("embedding", {}),
            "recognition": entry.payload.get("recognition", {}),
            "semantic": entry.payload.get("semantic", {}),
            "duplicates": entry.payload.get("duplicates", []),
            "tags": tags,
            "caption": caption,
            "provenance": list(entry.provenance),
            "scores": {
                "confidence": entry.confidence_score,
                "quality": entry.quality_score,
                "completeness": entry.completeness_score,
            },
        }
        formatted_payload = format_handler.build_payload(base_payload)

        provenance = list(entry.provenance)
        provenance.append(f"export:{format_type.value}")

        return ExportRecord(
            image_id=entry.image_id,
            path=Path(entry.path),
            format_type=format_type,
            payload=formatted_payload,
            caption=caption,
            tags=tags,
            provenance=provenance,
        )


def _caption_from_entry(entry: DatasetEntry, *, semantic: dict | None, tags: list[str]) -> str:
    semantic_payload = semantic or {}
    for key in ("caption", "prompt"):
        value = semantic_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    entry_semantic = entry.payload.get("semantic", {})
    if isinstance(entry_semantic, dict):
        for key in ("caption", "prompt"):
            value = entry_semantic.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    recognition = entry.payload.get("recognition", {})
    series = recognition.get("series") if isinstance(recognition, dict) else None
    characters = recognition.get("characters") if isinstance(recognition, dict) else []
    if not isinstance(characters, list):
        characters = []

    parts: list[str] = []
    if isinstance(series, str) and series.strip():
        parts.append(series.strip())

    char_values = [str(item).strip() for item in characters if str(item).strip()]
    if char_values:
        parts.append(", ".join(char_values))

    if tags:
        parts.append(", ".join(tags[:8]))

    if not parts:
        image_payload = entry.payload.get("image", {})
        filename = image_payload.get("filename") if isinstance(image_payload, dict) else None
        if isinstance(filename, str) and filename.strip():
            parts.append(filename.strip())

    return " | ".join(parts)
