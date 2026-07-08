from __future__ import annotations

from copy import deepcopy

from engine.knowledge_packs.knowledge_pack_builder import KnowledgePackBuilder
from engine.knowledge_packs.knowledge_pack_exceptions import (
    KnowledgePackConflictError,
    KnowledgePackDependencyError,
    KnowledgePackIntegrityError,
    KnowledgePackNotFoundError,
    KnowledgePackStorageLimitError,
)
from engine.knowledge_packs.knowledge_pack_models import KnowledgePackConflict, KnowledgePackManifest, KnowledgePackOperationResult


MAX_INSTALLED_STORAGE_BYTES = 5 * 1024 * 1024 * 1024


class KnowledgePackRepository:
    """Repository facade for installed downloadable external knowledge packs."""

    def __init__(self, *, builder: KnowledgePackBuilder | None = None) -> None:
        self.builder = builder or KnowledgePackBuilder()
        self._installed: dict[str, KnowledgePackManifest] = {}
        self._history: dict[str, list[KnowledgePackManifest]] = {}

    def install_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        self.verify_checksum(manifest)
        self.resolve_dependencies(manifest.dependencies)
        if manifest.pack_id in self._installed:
            raise KnowledgePackConflictError(f"Pack already installed: {manifest.pack_id}")

        self._enforce_storage_limit(incoming=manifest)
        self._installed[manifest.pack_id] = deepcopy(manifest)
        self._history.setdefault(manifest.pack_id, []).append(deepcopy(manifest))
        return KnowledgePackOperationResult(action="install", pack_id=manifest.pack_id, success=True)

    def uninstall_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        self._require(pack_id)
        del self._installed[pack_id]
        return KnowledgePackOperationResult(action="uninstall", pack_id=pack_id, success=True)

    def enable_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        pack = self._require(pack_id)
        pack.enabled = True
        return KnowledgePackOperationResult(action="enable", pack_id=pack_id, success=True)

    def disable_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        pack = self._require(pack_id)
        pack.enabled = False
        return KnowledgePackOperationResult(action="disable", pack_id=pack_id, success=True)

    def verify_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        pack = self._require(pack_id)
        self.verify_checksum(pack)
        return KnowledgePackOperationResult(action="verify", pack_id=pack_id, success=True)

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
    ) -> KnowledgePackManifest:
        target = self._require(target_pack_id)
        entries = deepcopy(target.entries)
        conflicts: list[KnowledgePackConflict] = []
        for pack_id in source_pack_ids:
            source_pack = self._require(pack_id)
            merge_resolution = "prefer_target" if resolution != "prefer_incoming" else "prefer_incoming"
            entries, found = self.builder.merge_entries(
                base_entries=entries,
                incoming_entries=source_pack.entries,
                existing_pack_id=target_pack_id,
                incoming_pack_id=source_pack.pack_id,
                resolution=merge_resolution,
            )
            conflicts.extend(found)

        merged = KnowledgePackManifest(
            pack_id=merged_pack_id,
            version=version,
            domain=target.domain,
            author=author,
            source=source,
            checksum="",
            signature="",
            compression=target.compression,
            metadata={"merged_from": [target_pack_id, *source_pack_ids]},
            dependencies=sorted(set(target.dependencies)),
            priority=max([target.priority, *[self._require(item).priority for item in source_pack_ids]]),
            incremental_from=None,
            installed_size_bytes=sum(self._require(item).installed_size_bytes for item in [target_pack_id, *source_pack_ids]),
            compressed_size_bytes=sum(self._require(item).compressed_size_bytes for item in [target_pack_id, *source_pack_ids]),
            enabled=True,
            entries=entries,
        )
        merged.checksum = self.builder.compute_checksum(merged)
        merged.signature = f"sig:{merged.pack_id}:{merged.version}"
        self._enforce_storage_limit(incoming=merged)
        self._installed[merged.pack_id] = deepcopy(merged)
        self._history.setdefault(merged.pack_id, []).append(deepcopy(merged))
        if conflicts and resolution not in {"prefer_target", "prefer_incoming"}:
            raise KnowledgePackConflictError("Unable to merge due to unresolved conflicts")
        return merged

    def import_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        if manifest.pack_id in self._installed:
            return self.update_pack(manifest)
        return self.install_pack(manifest)

    def export_pack(self, pack_id: str) -> KnowledgePackManifest:
        return deepcopy(self._require(pack_id))

    def update_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        current = self._require(manifest.pack_id)
        self.verify_checksum(manifest)
        self.resolve_dependencies(manifest.dependencies)
        if self.builder.compare_semver(manifest.version, current.version) < 0:
            raise KnowledgePackConflictError(
                f"Version downgrade is not allowed via update: {manifest.version} < {current.version}"
            )
        if manifest.incremental_from is not None and manifest.incremental_from != current.version:
            raise KnowledgePackConflictError(
                f"Incremental update expects {manifest.incremental_from}, found {current.version}"
            )
        self._enforce_storage_limit(incoming=manifest, replacing_pack_id=manifest.pack_id)
        self._history.setdefault(manifest.pack_id, []).append(deepcopy(current))
        self._installed[manifest.pack_id] = deepcopy(manifest)
        return KnowledgePackOperationResult(action="update", pack_id=manifest.pack_id, success=True)

    def rollback_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        self._require(pack_id)
        history = self._history.get(pack_id, [])
        if not history:
            raise KnowledgePackConflictError(f"No rollback snapshot available: {pack_id}")
        previous = history.pop()
        self._installed[pack_id] = deepcopy(previous)
        return KnowledgePackOperationResult(
            action="rollback",
            pack_id=pack_id,
            success=True,
            details={"rolled_back_to": previous.version},
        )

    def verify_checksum(self, manifest: KnowledgePackManifest) -> None:
        if not self.builder.verify_checksum(manifest):
            raise KnowledgePackIntegrityError(f"Checksum verification failed for {manifest.pack_id}")

    def detect_conflicts(self, manifest: KnowledgePackManifest) -> list[KnowledgePackConflict]:
        conflicts: list[KnowledgePackConflict] = []
        incoming_ids = {entry.canonical_id for entry in manifest.entries}
        for existing in self._installed.values():
            if not existing.enabled:
                continue
            existing_ids = {entry.canonical_id for entry in existing.entries}
            for canonical_id in sorted(incoming_ids & existing_ids):
                conflicts.append(
                    KnowledgePackConflict(
                        canonical_id=canonical_id,
                        existing_pack_id=existing.pack_id,
                        incoming_pack_id=manifest.pack_id,
                        resolution="priority",
                    )
                )
        return conflicts

    def resolve_dependencies(self, dependencies: list[str]) -> None:
        missing = [dependency for dependency in dependencies if dependency not in self._installed]
        if missing:
            raise KnowledgePackDependencyError(f"Missing dependencies: {', '.join(sorted(missing))}")

    def list_installed_packs(self) -> list[KnowledgePackManifest]:
        return [deepcopy(self._installed[key]) for key in sorted(self._installed)]

    def list_enabled_packs(self) -> list[KnowledgePackManifest]:
        return [
            deepcopy(manifest)
            for manifest in sorted(self._installed.values(), key=lambda item: (-item.priority, item.pack_id))
            if manifest.enabled
        ]

    def get_pack(self, pack_id: str) -> KnowledgePackManifest | None:
        pack = self._installed.get(pack_id)
        return None if pack is None else deepcopy(pack)

    def total_installed_size_bytes(self) -> int:
        return sum(max(0, item.installed_size_bytes) for item in self._installed.values())

    def _require(self, pack_id: str) -> KnowledgePackManifest:
        pack = self._installed.get(pack_id)
        if pack is None:
            raise KnowledgePackNotFoundError(f"Knowledge pack not found: {pack_id}")
        return pack

    def _enforce_storage_limit(self, *, incoming: KnowledgePackManifest, replacing_pack_id: str | None = None) -> None:
        current_size = self.total_installed_size_bytes()
        if replacing_pack_id is not None and replacing_pack_id in self._installed:
            current_size -= max(0, self._installed[replacing_pack_id].installed_size_bytes)
        projected = current_size + max(0, incoming.installed_size_bytes)
        if projected > MAX_INSTALLED_STORAGE_BYTES:
            raise KnowledgePackStorageLimitError(
                f"Installed knowledge pack size would exceed 5 GB ({projected} bytes)"
            )
