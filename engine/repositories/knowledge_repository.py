from __future__ import annotations

from engine.database.models.knowledge import Knowledge
from engine.repositories.base_repository import BaseRepository


class KnowledgeRepository(BaseRepository[Knowledge]):
    """Repository for knowledge persistence operations."""

    def __init__(self) -> None:
        super().__init__(Knowledge)

    def create_version(self, *, version: str, description: str | None = None, created_by: str | None = None) -> Knowledge:
        knowledge = Knowledge(version=version, description=description, created_by=created_by)
        self.add(knowledge)
        self.commit()
        return knowledge

    def current_version(self) -> Knowledge | None:
        return self.session.query(Knowledge).order_by(Knowledge.created_at.desc()).first()

    def add_alias(self, knowledge: Knowledge, alias: str) -> Knowledge:
        if knowledge.description is None:
            knowledge.description = alias
        else:
            knowledge.description = f"{knowledge.description}; {alias}"
        self.commit()
        return knowledge

    def remove_alias(self, knowledge: Knowledge, alias: str) -> Knowledge:
        if knowledge.description is None:
            return knowledge
        parts = [part for part in knowledge.description.split(";") if part.strip() != alias]
        knowledge.description = "; ".join(parts) if parts else None
        self.commit()
        return knowledge
