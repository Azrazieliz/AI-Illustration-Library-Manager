from __future__ import annotations

from engine.knowledge_packs.knowledge_pack_engine import KnowledgePackEngine
from engine.knowledge_packs.knowledge_pack_models import KnowledgePackLookupResult, KnowledgePackManifest, KnowledgePackOperationResult
from engine.knowledge_packs.knowledge_pack_statistics import KnowledgePackStatistics


class KnowledgePackService:
    """Service facade for external downloadable knowledge pack operations."""

    def __init__(self, *, engine: KnowledgePackEngine | None = None) -> None:
        self.engine = engine or KnowledgePackEngine(callback=self._handle_event)

    def install_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        return self.engine.install_pack(manifest)

    def uninstall_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        return self.engine.uninstall_pack(pack_id)

    def enable_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        return self.engine.enable_pack(pack_id)

    def disable_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        return self.engine.disable_pack(pack_id)

    def verify_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        return self.engine.verify_pack(pack_id)

    def update_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        return self.engine.update_pack(manifest)

    def rollback_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        return self.engine.rollback_pack(pack_id)

    def merge_packs(
        self,
        *,
        target_pack_id: str,
        source_pack_ids: list[str],
        merged_pack_id: str,
        version: str,
        author: str,
        source: str,
        resolution: str = "prefer_target",
    ) -> KnowledgePackOperationResult:
        return self.engine.merge_packs(
            target_pack_id=target_pack_id,
            source_pack_ids=source_pack_ids,
            merged_pack_id=merged_pack_id,
            version=version,
            author=author,
            source=source,
            resolution=resolution,
        )

    def lookup(self, canonical_or_alias: str, *, locale: str = "en") -> KnowledgePackLookupResult | None:
        return self.engine.lookup(canonical_or_alias, locale=locale)

    def statistics(self) -> KnowledgePackStatistics:
        return self.engine.snapshot_statistics()

    def _handle_event(self, event: object) -> None:
        return None
