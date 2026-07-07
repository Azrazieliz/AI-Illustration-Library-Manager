from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text

from engine.collections.collection_models import CollectionRecord
from engine.database.models.character import Character
from engine.database.models.embedding import Embedding
from engine.database.models.hash import HashModel
from engine.database.models.image import Image
from engine.database.models.job import Job
from engine.database.models.knowledge import Knowledge
from engine.database.models.metadata import MetadataRecord
from engine.database.models.review import Review
from engine.database.models.series import Series
from engine.database.models.tag import Tag
from engine.database.models.thumbnail import ThumbnailRecord
from engine.database.models.transaction import Transaction
from engine.export.export_models import ExportFormatType
from engine.repositories.collection_repository import CollectionRepository
from engine.repositories.dataset_repository import DatasetRepository
from engine.repositories.duplicate_repository import DuplicateRepository
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.export_repository import ExportRepository
from engine.repositories.hash_repository import HashRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.job_repository import JobRepository
from engine.repositories.knowledge_repository import KnowledgeRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.review_repository import ReviewRepository
from engine.repositories.search_repository import SearchRepository
from engine.repositories.tag_repository import TagRepository
from engine.repositories.thumbnail_repository import ThumbnailRepository


class MaintenanceRepository:
    """Read/write repository facade used by maintenance actions."""

    def __init__(self) -> None:
        self.image_repository = ImageRepository()
        self.metadata_repository = MetadataRepository()
        self.embedding_repository = EmbeddingRepository()
        self.thumbnail_repository = ThumbnailRepository()
        self.search_repository = SearchRepository()
        self.knowledge_repository = KnowledgeRepository()
        self.hash_repository = HashRepository()
        self.job_repository = JobRepository()
        self.review_repository = ReviewRepository()
        self.collection_repository = CollectionRepository()
        self.dataset_repository = DatasetRepository()
        self.export_repository = ExportRepository()
        self.duplicate_repository = DuplicateRepository()
        self.tag_repository = TagRepository()
        self.session = self.image_repository.session

    def scan_images(self) -> list[Image]:
        return list(self.session.query(Image).order_by(Image.id).all())

    def scan_metadata(self) -> list[MetadataRecord]:
        return list(self.session.query(MetadataRecord).order_by(MetadataRecord.id).all())

    def scan_embeddings(self) -> list[Embedding]:
        return list(self.session.query(Embedding).order_by(Embedding.id).all())

    def scan_thumbnails(self) -> list[ThumbnailRecord]:
        return list(self.session.query(ThumbnailRecord).order_by(ThumbnailRecord.id).all())

    def scan_hashes(self) -> list[HashModel]:
        return list(self.session.query(HashModel).order_by(HashModel.id).all())

    def scan_series(self) -> list[Series]:
        return list(self.session.query(Series).order_by(Series.id).all())

    def scan_characters(self) -> list[Character]:
        return list(self.session.query(Character).order_by(Character.id).all())

    def scan_reviews(self) -> list[Review]:
        return list(self.session.query(Review).order_by(Review.id).all())

    def scan_jobs(self) -> list[Job]:
        return list(self.session.query(Job).order_by(Job.id).all())

    def scan_transactions(self) -> list[Transaction]:
        return list(self.session.query(Transaction).order_by(Transaction.id).all())

    def scan_tags(self) -> list[Tag]:
        return list(self.session.query(Tag).order_by(Tag.id).all())

    def scan_collections(self) -> list[CollectionRecord]:
        rows = self.collection_repository.list_collections()
        rows.sort(key=lambda row: row.collection_id)
        return rows

    def scan_knowledge(self) -> list[Knowledge]:
        return list(self.session.query(Knowledge).order_by(Knowledge.id).all())

    def scan_dataset(self) -> dict[int, list[str]]:
        return {int(k): list(v) for k, v in self.dataset_repository._dataset_provenance.items()}

    def scan_exports(self) -> dict[str, Any]:
        return {
            "manifests": {k: dict(v) for k, v in self.export_repository._manifest_store.items()},
            "provenance": {k: list(v) for k, v in self.export_repository._provenance_store.items()},
            "formats": [item.value for item in ExportFormatType],
        }

    def repair_metadata(self, image_id: int) -> MetadataRecord:
        existing = self.metadata_repository.get_by_image_id(image_id)
        if existing is not None:
            return existing
        return self.metadata_repository.create_metadata_record(image_id=image_id, mime_type="image/unknown")

    def repair_embeddings(self, image_id: int, vector_path: str) -> Embedding:
        existing = self.embedding_repository.get_by_image_id(image_id)
        if existing is not None:
            existing.vector_path = vector_path
            self.session.commit()
            return existing
        record = self.embedding_repository.create_embedding_record(
            image_id=image_id,
            vector_path=vector_path,
            model_name="maintenance",
            model_version="1",
        )
        self.session.commit()
        return record

    def repair_thumbnails(self, image_id: int, file_path: str) -> ThumbnailRecord:
        rows = self.thumbnail_repository.list_by_image(image_id)
        if rows:
            rows[0].file_path = file_path
            rows[0].file_size_bytes = Path(file_path).stat().st_size if Path(file_path).exists() else 0
            self.session.commit()
            return rows[0]
        return self.thumbnail_repository.create_thumbnail_record(
            image_id=image_id,
            size=256,
            format="webp",
            file_path=file_path,
            file_size_bytes=Path(file_path).stat().st_size if Path(file_path).exists() else 0,
            cache_key=f"maintenance-{image_id}",
            thumb_width=64,
            thumb_height=64,
        )

    def repair_hashes(self, image_id: int, sha256: str) -> HashModel:
        existing = self.hash_repository.get_by_image_id(image_id)
        if existing is not None:
            existing.sha256 = sha256
            if existing.phash is None:
                existing.phash = sha256[:16]
            if existing.ahash is None:
                existing.ahash = sha256[16:32]
            if existing.dhash is None:
                existing.dhash = sha256[32:48]
            self.session.commit()
            return existing
        return self.hash_repository.create_hash_record(
            image_id=image_id,
            sha256=sha256,
            phash=sha256[:16],
            ahash=sha256[16:32],
            dhash=sha256[32:48],
        )

    def repair_search(self, image_id: int) -> Embedding | None:
        return self.search_repository.get_embedding_by_image_id(image_id)

    def repair_knowledge_graph(self) -> Knowledge:
        return self.knowledge_repository.create_version(version="maintenance-graph", description="rebuilt")

    def repair_database(self) -> None:
        self.session.execute(text("SELECT 1"))
        self.session.commit()

    def repair_queue(self) -> int:
        removed = 0
        for job in self.scan_jobs():
            if job.progress < 0 or job.progress > 100:
                job.progress = min(100, max(0, job.progress))
                removed += 1
            status = job.status.strip().lower()
            if status not in {"pending", "running", "finished", "cancelled", "failed"}:
                job.status = "failed"
                removed += 1
        self.session.commit()
        return removed

    def repair_statistics(self) -> dict[str, int]:
        images = self.scan_images()
        thumbnail_ids = {item.image_id for item in self.scan_thumbnails()}
        embedding_ids = {item.image_id for item in self.scan_embeddings()}

        repaired = 0
        for image in images:
            expected_thumb = image.id in thumbnail_ids
            expected_embed = image.id in embedding_ids
            if image.thumbnail_exists != expected_thumb:
                image.thumbnail_exists = expected_thumb
                repaired += 1
            if image.embedding_exists != expected_embed:
                image.embedding_exists = expected_embed
                repaired += 1
        self.session.commit()
        return {
            "repaired": repaired,
            "images": len(images),
        }

    def cleanup(self) -> int:
        removed = 0
        workspace = Path.cwd()
        for candidate in workspace.rglob("*.tmp"):
            if candidate.is_file():
                candidate.unlink(missing_ok=True)
                removed += 1
        for candidate in workspace.rglob("*.temp"):
            if candidate.is_file():
                candidate.unlink(missing_ok=True)
                removed += 1
        return removed
