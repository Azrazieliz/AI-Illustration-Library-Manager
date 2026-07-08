from __future__ import annotations

from time import perf_counter

from engine.knowledge_packs.knowledge_pack_builder import KnowledgePackBuilder
from engine.knowledge_packs.knowledge_pack_exceptions import KnowledgePackConflictError, KnowledgePackValidationError
from engine.knowledge_packs.knowledge_pack_models import KnowledgeEntry, KnowledgePackLookupResult, KnowledgePackManifest, KnowledgePackOperationResult
from engine.knowledge_packs.knowledge_pack_statistics import KnowledgePackStatistics
from engine.repositories.knowledge_pack_repository import KnowledgePackRepository


class KnowledgePackEngine:
    """Pack manager and update manager for downloadable canonical knowledge packs."""

    def __init__(
        self,
        *,
        repository: KnowledgePackRepository | None = None,
        builder: KnowledgePackBuilder | None = None,
        callback=None,
    ) -> None:
        self.repository = repository or KnowledgePackRepository()
        self.builder = builder or KnowledgePackBuilder()
        self.callback = callback
        self.statistics = KnowledgePackStatistics()
        self._active_registry: list[str] = []
        self._lookup_cache: dict[str, KnowledgePackLookupResult] = {}
        self._refresh_registry()

    def install_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        started = perf_counter()
        self.validate_pack(manifest)
        existing = self.repository.get_pack(manifest.pack_id)
        if existing is not None and existing.version == manifest.version and existing.checksum == manifest.checksum:
            self._after_operation(started)
            return KnowledgePackOperationResult(
                action="install",
                pack_id=manifest.pack_id,
                success=True,
                message="Pack already installed with identical version/checksum",
            )

        conflicts = [item for item in self.repository.detect_conflicts(manifest) if item.existing_pack_id != manifest.pack_id]
        if conflicts and any(manifest.priority <= self.repository.get_pack(item.existing_pack_id).priority for item in conflicts):
            raise KnowledgePackConflictError("Conflicts detected with equal or higher-priority packs")
        result = self.repository.install_pack(manifest)
        self.statistics.installs += 1
        self._after_operation(started)
        return result

    def uninstall_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        started = perf_counter()
        result = self.repository.uninstall_pack(pack_id)
        self.statistics.uninstalls += 1
        self._after_operation(started)
        return result

    def enable_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        started = perf_counter()
        result = self.repository.enable_pack(pack_id)
        self._after_operation(started)
        return result

    def disable_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        started = perf_counter()
        result = self.repository.disable_pack(pack_id)
        self._after_operation(started)
        return result

    def verify_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        started = perf_counter()
        result = self.repository.verify_pack(pack_id)
        self.statistics.verify_calls += 1
        self._after_operation(started)
        return result

    def update_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        started = perf_counter()
        self.validate_pack(manifest)
        result = self.repository.update_pack(manifest)
        self.statistics.updates += 1
        self._after_operation(started)
        return result

    def rollback_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        started = perf_counter()
        result = self.repository.rollback_pack(pack_id)
        self.statistics.rollbacks += 1
        self._after_operation(started)
        return result

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
        started = perf_counter()
        self.builder.validate_semver(version)
        merged = self.repository.merge_packs(
            target_pack_id=target_pack_id,
            source_pack_ids=source_pack_ids,
            merged_pack_id=merged_pack_id,
            version=version,
            author=author,
            source=source,
            resolution=resolution,
        )
        self.statistics.merges += 1
        self._after_operation(started)
        return KnowledgePackOperationResult(
            action="merge",
            pack_id=merged.pack_id,
            success=True,
            details={"version": merged.version, "merged_from": [target_pack_id, *source_pack_ids]},
        )

    def lookup(self, canonical_or_alias: str, *, locale: str = "en") -> KnowledgePackLookupResult | None:
        self.statistics.lookup_calls += 1
        cache_key = f"{canonical_or_alias}|{locale}"
        cached = self._lookup_cache.get(cache_key)
        if cached is not None:
            self.statistics.cache_hits += 1
            return cached
        self.statistics.cache_misses += 1

        query = canonical_or_alias.strip().lower()
        for pack in self.repository.list_enabled_packs():
            for entry in pack.entries:
                if self._entry_matches(entry, query=query, locale=locale):
                    result = KnowledgePackLookupResult(
                        canonical_id=entry.canonical_id,
                        pack_id=pack.pack_id,
                        canonical_name=entry.canonical_name,
                        localized_name=entry.localized_names.get(locale),
                        aliases=list(entry.aliases),
                        tags=list(entry.tags),
                        categories=list(entry.categories),
                    )
                    self._lookup_cache[cache_key] = result
                    return result
        return None

    def active_registry(self) -> list[str]:
        return list(self._active_registry)

    def list_installed(self) -> list[KnowledgePackManifest]:
        return self.repository.list_installed_packs()

    def list_enabled(self) -> list[KnowledgePackManifest]:
        return self.repository.list_enabled_packs()

    def invalidate_cache(self) -> None:
        self._lookup_cache.clear()

    def snapshot_statistics(self) -> KnowledgePackStatistics:
        self.statistics.active_packs = len(self._active_registry)
        self.statistics.total_installed_bytes = self.repository.total_installed_size_bytes()
        return KnowledgePackStatistics(**self.statistics.__dict__)

    def validate_pack(self, manifest: KnowledgePackManifest) -> None:
        self.builder.validate_semver(manifest.version)
        if not manifest.pack_id.strip():
            raise KnowledgePackValidationError("pack_id is required")
        if not manifest.author.strip():
            raise KnowledgePackValidationError("author is required")
        if not manifest.source.strip():
            raise KnowledgePackValidationError("source is required")
        if not manifest.signature.strip():
            raise KnowledgePackValidationError("signature is required")
        duplicates = self.builder.detect_duplicates(manifest.entries)
        if duplicates:
            raise KnowledgePackValidationError(
                f"Duplicate canonical ids in pack manifest: {', '.join(sorted(duplicates))}"
            )
        self.repository.verify_checksum(manifest)

    def _refresh_registry(self) -> None:
        self._active_registry = [pack.pack_id for pack in self.repository.list_enabled_packs()]

    def _after_operation(self, started: float) -> None:
        self.statistics.record_latency((perf_counter() - started) * 1000.0)
        self._refresh_registry()
        self.invalidate_cache()

    def _entry_matches(self, entry: KnowledgeEntry, *, query: str, locale: str) -> bool:
        if entry.canonical_id.lower() == query:
            return True
        if entry.canonical_name.lower() == query:
            return True
        localized = entry.localized_names.get(locale)
        if localized and localized.lower() == query:
            return True
        return any(alias.lower() == query for alias in entry.aliases)
