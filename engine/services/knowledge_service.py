from __future__ import annotations

from engine.database.models.knowledge import Knowledge
from engine.repositories.knowledge_repository import KnowledgeRepository
from engine.services.base_service import BaseService


class KnowledgeService(BaseService[Knowledge]):
    """Service layer for knowledge records."""

    def __init__(self, repository: KnowledgeRepository | None = None) -> None:
        super().__init__(repository or KnowledgeRepository())
        self.repository = repository or KnowledgeRepository()

    def create_version(self, *, version: str, description: str | None = None, created_by: str | None = None) -> Knowledge:
        return self.repository.create_version(version=version, description=description, created_by=created_by)

    def current_version(self) -> Knowledge | None:
        return self.repository.current_version()

    def add_alias(self, knowledge: Knowledge, alias: str) -> Knowledge:
        return self.repository.add_alias(knowledge, alias)

    def remove_alias(self, knowledge: Knowledge, alias: str) -> Knowledge:
        return self.repository.remove_alias(knowledge, alias)
