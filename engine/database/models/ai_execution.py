from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from engine.database.base import BaseModel


class AiExecutionRecord(BaseModel):
    """Append-only source-backed record for one completed AI runtime call."""

    __tablename__ = "ai_execution"

    task: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    runtime: Mapped[str] = mapped_column(String(128), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}

    @property
    def execution_uuid(self) -> str:
        return self.uuid