from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from engine.collections.collection_models import CollectionRecord
from engine.database.models.character import Character
from engine.database.models.embedding import Embedding
from engine.database.models.image import Image, image_character_association, image_tag_association
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
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.export_repository import ExportRepository
from engine.repositories.image_repository import ImageRepository
from engine.repositories.job_repository import JobRepository
from engine.repositories.knowledge_repository import KnowledgeRepository
from engine.repositories.metadata_repository import MetadataRepository
from engine.repositories.review_repository import ReviewRepository
from engine.repositories.thumbnail_repository import ThumbnailRepository


@dataclass(slots=True)
class PipelineSnapshot:
    jobs: list[Job]
    now: datetime


class IntegrityRepository:
    """Repository facade for integrity scanning over filesystem, DB, and in-memory stores."""

    def __init__(self) -> None:
        self.image_repository = ImageRepository()
        self.metadata_repository = MetadataRepository()
        self.embedding_repository = EmbeddingRepository()
        self.thumbnail_repository = ThumbnailRepository()
        self.knowledge_repository = KnowledgeRepository()
        self.review_repository = ReviewRepository()
        self.collection_repository = CollectionRepository()
        self.job_repository = JobRepository()
        self.dataset_repository = DatasetRepository()
        self.export_repository = ExportRepository()
        self.session = self.image_repository.session

    def scan_images(self) -> list[Image]:
        return list(self.session.query(Image).order_by(Image.id).all())

    def scan_metadata(self) -> list[MetadataRecord]:
        return list(self.session.query(MetadataRecord).order_by(MetadataRecord.id).all())

    def scan_embeddings(self) -> list[Embedding]:
        return list(self.session.query(Embedding).order_by(Embedding.id).all())

    def scan_thumbnails(self) -> list[ThumbnailRecord]:
        return list(self.session.query(ThumbnailRecord).order_by(ThumbnailRecord.id).all())

    def scan_knowledge(self) -> list[Knowledge]:
        return list(self.session.query(Knowledge).order_by(Knowledge.id).all())

    def scan_series(self) -> list[Series]:
        return list(self.session.query(Series).order_by(Series.id).all())

    def scan_characters(self) -> list[Character]:
        return list(self.session.query(Character).order_by(Character.id).all())

    def scan_tags(self) -> list[Tag]:
        return list(self.session.query(Tag).order_by(Tag.id).all())

    def scan_transactions(self) -> list[Transaction]:
        return list(self.session.query(Transaction).order_by(Transaction.id).all())

    def scan_reviews(self) -> tuple[list[Review], list[Any]]:
        db_reviews = list(self.session.query(Review).order_by(Review.id).all())
        queue_reviews = self.review_repository.list_review_items()
        queue_reviews.sort(key=lambda item: item.review_id)
        return db_reviews, queue_reviews

    def scan_collections(self) -> list[CollectionRecord]:
        rows = self.collection_repository.list_collections()
        rows.sort(key=lambda item: item.collection_id)
        return rows

    def scan_pipeline(self) -> PipelineSnapshot:
        jobs = list(self.session.query(Job).order_by(Job.id).all())
        return PipelineSnapshot(jobs=jobs, now=datetime.now(timezone.utc))

    def scan_dataset(self) -> dict[int, list[str]]:
        return {int(key): list(value) for key, value in self.dataset_repository._dataset_provenance.items()}

    def scan_exports(self) -> dict[str, Any]:
        manifests: dict[tuple[str, int], dict[str, Any]] = {
            key: dict(value)
            for key, value in self.export_repository._manifest_store.items()
        }
        provenance: dict[tuple[str, int], list[str]] = {
            key: list(value)
            for key, value in self.export_repository._provenance_store.items()
        }
        known_formats = [item.value for item in ExportFormatType]
        return {
            "manifests": manifests,
            "provenance": provenance,
            "known_formats": known_formats,
        }

    def scan_database(self) -> dict[str, list[Any]]:
        image_links = self.session.execute(image_character_association.select()).all()
        tag_links = self.session.execute(image_tag_association.select()).all()
        return {
            "images": self.scan_images(),
            "metadata": self.scan_metadata(),
            "embeddings": self.scan_embeddings(),
            "thumbnails": self.scan_thumbnails(),
            "knowledge": self.scan_knowledge(),
            "series": self.scan_series(),
            "characters": self.scan_characters(),
            "tags": self.scan_tags(),
            "transactions": self.scan_transactions(),
            "reviews": list(self.session.query(Review).order_by(Review.id).all()),
            "jobs": list(self.session.query(Job).order_by(Job.id).all()),
            "image_character_links": image_links,
            "image_tag_links": tag_links,
        }
