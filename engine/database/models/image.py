from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from engine.database.base import BaseModel

if TYPE_CHECKING:
    from engine.database.models.character import Character
    from engine.database.models.embedding import Embedding
    from engine.database.models.hash import HashModel
    from engine.database.models.metadata import MetadataRecord
    from engine.database.models.review import Review
    from engine.database.models.series import Series
    from engine.database.models.tag import Tag
    from engine.database.models.transaction import Transaction

image_character_association = Table(
    "image_character_association",
    BaseModel.metadata,
    Column("image_id", Integer, ForeignKey("image.id"), primary_key=True),
    Column("character_id", Integer, ForeignKey("character.id"), primary_key=True),
)

image_tag_association = Table(
    "image_tag_association",
    BaseModel.metadata,
    Column("image_id", Integer, ForeignKey("image.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tag.id"), primary_key=True),
)


class Image(BaseModel):
    """Represents an indexed image in the library."""

    __tablename__ = "image"

    original_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    current_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(16), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filesize: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id"), nullable=True)
    sfw_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thumbnail_exists: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    embedding_exists: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scan_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    series: Mapped["Series | None"] = relationship(back_populates="images")
    characters: Mapped[list["Character"]] = relationship(secondary=image_character_association, back_populates="images")
    tags: Mapped[list["Tag"]] = relationship(secondary=image_tag_association, back_populates="images")
    embedding: Mapped["Embedding | None"] = relationship(back_populates="image", cascade="all, delete-orphan")
    hash_record: Mapped["HashModel | None"] = relationship(back_populates="image", cascade="all, delete-orphan")
    metadata_record: Mapped["MetadataRecord | None"] = relationship(back_populates="image", cascade="all, delete-orphan")
    reviews: Mapped[list["Review"]] = relationship(back_populates="image", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="image", cascade="all, delete-orphan")
