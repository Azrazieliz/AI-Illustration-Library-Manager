from __future__ import annotations

from pathlib import Path

from engine.dataset.dataset_models import DatasetEntry
from engine.repositories.dataset_repository import DatasetRepository


class DatasetBuilder:
    """Builds canonical dataset entries from processed subsystem outputs."""

    def __init__(self, repository: DatasetRepository | None = None) -> None:
        self.repository = repository or DatasetRepository()

    def build(self, path: str | Path, *, semantic: dict | None = None) -> DatasetEntry | None:
        image = self.repository.get_image_by_path(path)
        if image is None:
            return None

        metadata = self.repository.get_metadata_by_image_id(image.id)
        hash_record = self.repository.get_hash_by_image_id(image.id)
        embedding = self.repository.get_embedding_by_image_id(image.id)
        tags = self.repository.get_tags_for_image(image.id)
        duplicates = self.repository.get_duplicates_for_image(image.id)

        recognition = {
            "series": image.series.name if image.series is not None else None,
            "characters": [character.name for character in image.characters],
        }

        payload = {
            "image": {
                "id": image.id,
                "path": image.original_path,
                "filename": image.filename,
                "extension": image.extension,
                "width": image.width,
                "height": image.height,
            },
            "metadata": {
                "mime_type": metadata.mime_type if metadata else None,
                "orientation": metadata.orientation if metadata else None,
                "color_mode": metadata.color_mode if metadata else None,
                "is_animated": metadata.is_animated if metadata else False,
            },
            "hashes": {
                "sha256": hash_record.sha256 if hash_record else None,
                "phash": hash_record.phash if hash_record else None,
            },
            "embedding": {
                "model_name": embedding.model_name if embedding else None,
                "model_version": embedding.model_version if embedding else None,
                "vector_path": embedding.vector_path if embedding else None,
            },
            "recognition": recognition,
            "semantic": semantic or {},
            "tags": [
                {
                    "name": tag.name,
                    "category": tag.category,
                }
                for tag in tags
            ],
            "duplicates": [
                {
                    "image_a_id": duplicate.image_a_id,
                    "image_b_id": duplicate.image_b_id,
                    "overall_score": duplicate.overall_score,
                    "match_type": duplicate.match_type,
                }
                for duplicate in duplicates
            ],
        }

        confidence_score = _confidence_score(payload)
        quality_score = _quality_score(payload)
        completeness_score = _completeness_score(payload)
        provenance = _provenance(payload)

        return DatasetEntry(
            image_id=image.id,
            path=Path(image.original_path),
            payload=payload,
            confidence_score=confidence_score,
            quality_score=quality_score,
            completeness_score=completeness_score,
            provenance=provenance,
        )


def _confidence_score(payload: dict) -> float:
    score = 0.4
    if payload["recognition"]["series"]:
        score += 0.2
    if payload["recognition"]["characters"]:
        score += 0.15
    if payload["tags"]:
        score += 0.15
    if payload["embedding"]["model_name"]:
        score += 0.1
    return min(1.0, round(score, 4))


def _quality_score(payload: dict) -> float:
    image = payload["image"]
    width = image["width"] or 0
    height = image["height"] or 0
    pixels = width * height
    if pixels <= 0:
        return 0.3
    if pixels < 256 * 256:
        return 0.5
    if pixels < 1024 * 1024:
        return 0.75
    return 0.9


def _completeness_score(payload: dict) -> float:
    fields = [
        payload["image"]["path"],
        payload["metadata"]["mime_type"],
        payload["hashes"]["sha256"],
        payload["embedding"]["model_name"],
        payload["tags"],
    ]
    present = sum(1 for field in fields if field)
    return round(present / len(fields), 4)


def _provenance(payload: dict) -> list[str]:
    out: list[str] = ["dataset_builder"]
    if payload["metadata"]["mime_type"]:
        out.append("metadata")
    if payload["hashes"]["sha256"]:
        out.append("hashing")
    if payload["embedding"]["model_name"]:
        out.append("embedding")
    if payload["recognition"]["series"] or payload["recognition"]["characters"]:
        out.append("recognition")
    if payload["tags"]:
        out.append("tagging")
    if payload["duplicates"]:
        out.append("duplicates")
    if payload["semantic"]:
        out.append("semantic")
    return out
