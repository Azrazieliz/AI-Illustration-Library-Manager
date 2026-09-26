from __future__ import annotations

import hashlib
from math import isfinite
from pathlib import Path

from sqlalchemy.orm import Session

from engine.database.models.ai_execution import AiExecutionRecord
from engine.repositories.base_repository import BaseRepository


class AiExecutionRepository(BaseRepository[AiExecutionRecord]):
    """Repository for immutable AI execution audit records."""

    def __init__(self, session: Session | None = None) -> None:
        super().__init__(AiExecutionRecord, session=session)

    def append(
        self,
        *,
        task: str,
        model: str,
        model_version: str,
        runtime: str,
        input_hash: str | None,
        output_hash: str | None,
        duration: float,
        status: str,
        error: str | None = None,
    ) -> AiExecutionRecord:
        if not all(isinstance(value, str) and value.strip() for value in (task, model, model_version, runtime, status)):
            raise ValueError("AI execution task, model, model version, runtime, and status must be non-empty strings")
        if not isfinite(duration) or duration < 0:
            raise ValueError("AI execution duration must be finite and non-negative")
        for label, value in (("input_hash", input_hash), ("output_hash", output_hash)):
            if value is not None and (len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower())):
                raise ValueError(f"{label} must be a SHA-256 hexadecimal digest when provided")
        record = AiExecutionRecord(
            task=task,
            model=model,
            model_version=model_version,
            runtime=runtime,
            input_hash=input_hash,
            output_hash=output_hash,
            duration=duration,
            status=status,
            error=error,
        )
        self.add(record)
        return record

    def list_records(self) -> list[AiExecutionRecord]:
        return list(self.session.query(AiExecutionRecord).order_by(AiExecutionRecord.id).all())

    @staticmethod
    def hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()