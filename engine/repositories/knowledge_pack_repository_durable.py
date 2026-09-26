from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any

from sqlalchemy import delete, select, update

from engine.database.models.knowledge_pack_state import KnowledgePackStateRecord
from engine.database.session import session_scope
from engine.knowledge_packs.knowledge_pack_models import (
    KnowledgeEntry,
    KnowledgePackCompression,
    KnowledgePackDomain,
    KnowledgePackManifest,
    KnowledgePackOperationResult,
    KnowledgeRelationship,
)
from engine.repositories.knowledge_pack_repository import InMemoryKnowledgePackRepository


class DurableKnowledgePackRepository(InMemoryKnowledgePackRepository):
    """Versioned persistence for locally managed knowledge-pack installation state."""

    _state_key = "default"
    _state_lock = RLock()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lock = self._state_lock
        self._state_version: int | None = None
        self._load_state()

    @classmethod
    def reset_state(cls) -> None:
        with cls._state_lock, session_scope() as session:
            session.execute(delete(KnowledgePackStateRecord))

    def install_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        with self._lock:
            result = super().install_pack(manifest)
            self._persist_state()
            return result

    def uninstall_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        with self._lock:
            result = super().uninstall_pack(pack_id)
            self._persist_state()
            return result

    def enable_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        with self._lock:
            result = super().enable_pack(pack_id)
            self._persist_state()
            return result

    def disable_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        with self._lock:
            result = super().disable_pack(pack_id)
            self._persist_state()
            return result

    def merge_packs(self, **kwargs: Any) -> KnowledgePackManifest:
        with self._lock:
            result = super().merge_packs(**kwargs)
            self._persist_state()
            return result

    def update_pack(self, manifest: KnowledgePackManifest) -> KnowledgePackOperationResult:
        with self._lock:
            result = super().update_pack(manifest)
            self._persist_state()
            return result

    def rollback_pack(self, pack_id: str) -> KnowledgePackOperationResult:
        with self._lock:
            result = super().rollback_pack(pack_id)
            self._persist_state()
            return result

    def get_pack(self, pack_id: str) -> KnowledgePackManifest | None:
        with self._lock:
            return super().get_pack(pack_id)

    def list_installed_packs(self) -> list[KnowledgePackManifest]:
        with self._lock:
            return super().list_installed_packs()

    def list_enabled_packs(self) -> list[KnowledgePackManifest]:
        with self._lock:
            return super().list_enabled_packs()

    def total_installed_size_bytes(self) -> int:
        with self._lock:
            return super().total_installed_size_bytes()

    def _load_state(self) -> None:
        with self._lock, session_scope() as session:
            row = session.scalar(
                select(KnowledgePackStateRecord).where(KnowledgePackStateRecord.state_key == self._state_key)
            )
            if row is None:
                return
            self._state_version = row.version
            self._restore_state(dict(row.state_payload or {}))

    def _persist_state(self) -> None:
        payload = self._state_payload()
        with session_scope() as session:
            row = session.scalar(
                select(KnowledgePackStateRecord).where(KnowledgePackStateRecord.state_key == self._state_key)
            )
            if row is None:
                if self._state_version is not None:
                    raise RuntimeError("Knowledge-pack state was removed while this repository was active")
                row = KnowledgePackStateRecord(state_key=self._state_key, state_payload=payload)
                session.add(row)
                session.flush()
                self._state_version = row.version
                return
            if self._state_version is None or row.version != self._state_version:
                raise RuntimeError("Knowledge-pack state changed in another repository instance; reload before writing")
            result = session.execute(
                update(KnowledgePackStateRecord)
                .where(
                    KnowledgePackStateRecord.id == row.id,
                    KnowledgePackStateRecord.version == self._state_version,
                )
                .values(
                    state_payload=payload,
                    version=KnowledgePackStateRecord.version + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if int(result.rowcount or 0) != 1:
                raise RuntimeError("Knowledge-pack state changed concurrently; retry the operation")
            self._state_version += 1

    def _state_payload(self) -> dict[str, Any]:
        return {
            "installed": {
                pack_id: self._manifest_to_payload(manifest)
                for pack_id, manifest in sorted(self._installed.items())
            },
            "history": {
                pack_id: [self._manifest_to_payload(manifest) for manifest in history]
                for pack_id, history in sorted(self._history.items())
            },
        }

    def _restore_state(self, payload: dict[str, Any]) -> None:
        installed = dict(payload.get("installed", {}))
        history = dict(payload.get("history", {}))
        self._installed = {
            str(pack_id): self._manifest_from_payload(manifest)
            for pack_id, manifest in installed.items()
            if isinstance(manifest, dict)
        }
        self._history = {
            str(pack_id): [
                self._manifest_from_payload(manifest)
                for manifest in snapshots
                if isinstance(manifest, dict)
            ]
            for pack_id, snapshots in history.items()
            if isinstance(snapshots, list)
        }

    @staticmethod
    def _manifest_to_payload(manifest: KnowledgePackManifest) -> dict[str, Any]:
        return {
            "pack_id": manifest.pack_id,
            "version": manifest.version,
            "domain": manifest.domain.value,
            "author": manifest.author,
            "source": manifest.source,
            "checksum": manifest.checksum,
            "signature": manifest.signature,
            "compression": manifest.compression.value,
            "metadata": dict(manifest.metadata),
            "dependencies": list(manifest.dependencies),
            "priority": manifest.priority,
            "incremental_from": manifest.incremental_from,
            "installed_size_bytes": manifest.installed_size_bytes,
            "compressed_size_bytes": manifest.compressed_size_bytes,
            "enabled": manifest.enabled,
            "created_at": manifest.created_at.isoformat(),
            "entries": [
                {
                    "canonical_id": entry.canonical_id,
                    "canonical_name": entry.canonical_name,
                    "localized_names": dict(entry.localized_names),
                    "aliases": list(entry.aliases),
                    "tags": list(entry.tags),
                    "categories": list(entry.categories),
                    "relationships": [
                        {
                            "source_id": relationship.source_id,
                            "target_id": relationship.target_id,
                            "relation": relationship.relation,
                        }
                        for relationship in entry.relationships
                    ],
                    "metadata": dict(entry.metadata),
                }
                for entry in manifest.entries
            ],
        }

    @classmethod
    def _manifest_from_payload(cls, payload: dict[str, Any]) -> KnowledgePackManifest:
        return KnowledgePackManifest(
            pack_id=str(payload.get("pack_id", "")),
            version=str(payload.get("version", "")),
            domain=KnowledgePackDomain(str(payload.get("domain", KnowledgePackDomain.CUSTOM.value))),
            author=str(payload.get("author", "")),
            source=str(payload.get("source", "")),
            checksum=str(payload.get("checksum", "")),
            signature=str(payload.get("signature", "")),
            compression=KnowledgePackCompression(str(payload.get("compression", KnowledgePackCompression.GZIP.value))),
            metadata=dict(payload.get("metadata", {})),
            dependencies=[str(item) for item in payload.get("dependencies", [])],
            priority=int(payload.get("priority", 0)),
            incremental_from=payload.get("incremental_from"),
            installed_size_bytes=int(payload.get("installed_size_bytes", 0)),
            compressed_size_bytes=int(payload.get("compressed_size_bytes", 0)),
            enabled=bool(payload.get("enabled", True)),
            entries=[
                KnowledgeEntry(
                    canonical_id=str(entry.get("canonical_id", "")),
                    canonical_name=str(entry.get("canonical_name", "")),
                    localized_names={str(key): str(value) for key, value in dict(entry.get("localized_names", {})).items()},
                    aliases=[str(item) for item in entry.get("aliases", [])],
                    tags=[str(item) for item in entry.get("tags", [])],
                    categories=[str(item) for item in entry.get("categories", [])],
                    relationships=[
                        KnowledgeRelationship(
                            source_id=str(relationship.get("source_id", "")),
                            target_id=str(relationship.get("target_id", "")),
                            relation=str(relationship.get("relation", "")),
                        )
                        for relationship in entry.get("relationships", [])
                        if isinstance(relationship, dict)
                    ],
                    metadata=dict(entry.get("metadata", {})),
                )
                for entry in payload.get("entries", [])
                if isinstance(entry, dict)
            ],
            created_at=cls._as_utc(payload.get("created_at")),
        )

    @staticmethod
    def _as_utc(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                return datetime.now(timezone.utc)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)