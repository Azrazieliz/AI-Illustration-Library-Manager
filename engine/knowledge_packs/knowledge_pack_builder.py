from __future__ import annotations

import gzip
import hashlib
import json
import lzma
import re
import zlib
from copy import deepcopy

from engine.knowledge_packs.knowledge_pack_exceptions import KnowledgePackValidationError
from engine.knowledge_packs.knowledge_pack_models import KnowledgeEntry, KnowledgePackCompression, KnowledgePackConflict, KnowledgePackManifest


_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class KnowledgePackBuilder:
    """Build and validate deterministic payloads for external knowledge packs."""

    def validate_semver(self, version: str) -> None:
        if not _SEMVER_PATTERN.fullmatch(version.strip()):
            raise KnowledgePackValidationError(f"Invalid semantic version: {version}")

    def semver_tuple(self, version: str) -> tuple[int, int, int, str, str]:
        self.validate_semver(version)
        match = _SEMVER_PATTERN.fullmatch(version.strip())
        assert match is not None
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        prerelease = match.group(4) or ""
        build = match.group(5) or ""
        return major, minor, patch, prerelease, build

    def compare_semver(self, left: str, right: str) -> int:
        left_tuple = self.semver_tuple(left)
        right_tuple = self.semver_tuple(right)
        if left_tuple[:3] < right_tuple[:3]:
            return -1
        if left_tuple[:3] > right_tuple[:3]:
            return 1
        left_pre = left_tuple[3]
        right_pre = right_tuple[3]
        if left_pre == right_pre:
            return 0
        if left_pre == "":
            return 1
        if right_pre == "":
            return -1
        return -1 if left_pre < right_pre else 1

    def payload_for_checksum(self, manifest: KnowledgePackManifest) -> bytes:
        payload = {
            "pack_id": manifest.pack_id,
            "version": manifest.version,
            "domain": manifest.domain.value,
            "author": manifest.author,
            "source": manifest.source,
            "compression": manifest.compression.value,
            "metadata": manifest.metadata,
            "dependencies": sorted(set(manifest.dependencies)),
            "priority": manifest.priority,
            "incremental_from": manifest.incremental_from,
            "installed_size_bytes": manifest.installed_size_bytes,
            "compressed_size_bytes": manifest.compressed_size_bytes,
            "enabled": manifest.enabled,
            "entries": [
                {
                    "canonical_id": entry.canonical_id,
                    "canonical_name": entry.canonical_name,
                    "localized_names": entry.localized_names,
                    "aliases": sorted(set(entry.aliases)),
                    "tags": sorted(set(entry.tags)),
                    "categories": sorted(set(entry.categories)),
                    "relationships": [
                        {
                            "source_id": relation.source_id,
                            "target_id": relation.target_id,
                            "relation": relation.relation,
                        }
                        for relation in entry.relationships
                    ],
                    "metadata": entry.metadata,
                }
                for entry in manifest.entries
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def compute_checksum(self, manifest: KnowledgePackManifest) -> str:
        return hashlib.sha256(self.payload_for_checksum(manifest)).hexdigest()

    def verify_checksum(self, manifest: KnowledgePackManifest) -> bool:
        return manifest.checksum == self.compute_checksum(manifest)

    def compress_payload(self, payload: bytes, compression: KnowledgePackCompression) -> bytes:
        if compression == KnowledgePackCompression.NONE:
            return payload
        if compression == KnowledgePackCompression.GZIP:
            return gzip.compress(payload)
        if compression == KnowledgePackCompression.ZLIB:
            return zlib.compress(payload)
        if compression == KnowledgePackCompression.LZMA:
            return lzma.compress(payload)
        raise KnowledgePackValidationError(f"Unsupported compression: {compression}")

    def decompress_payload(self, payload: bytes, compression: KnowledgePackCompression) -> bytes:
        if compression == KnowledgePackCompression.NONE:
            return payload
        if compression == KnowledgePackCompression.GZIP:
            return gzip.decompress(payload)
        if compression == KnowledgePackCompression.ZLIB:
            return zlib.decompress(payload)
        if compression == KnowledgePackCompression.LZMA:
            return lzma.decompress(payload)
        raise KnowledgePackValidationError(f"Unsupported compression: {compression}")

    def detect_duplicates(self, entries: list[KnowledgeEntry]) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for entry in entries:
            if entry.canonical_id in seen:
                duplicates.add(entry.canonical_id)
            seen.add(entry.canonical_id)
        return duplicates

    def merge_entries(
        self,
        *,
        base_entries: list[KnowledgeEntry],
        incoming_entries: list[KnowledgeEntry],
        existing_pack_id: str,
        incoming_pack_id: str,
        resolution: str,
    ) -> tuple[list[KnowledgeEntry], list[KnowledgePackConflict]]:
        merged: dict[str, KnowledgeEntry] = {entry.canonical_id: deepcopy(entry) for entry in base_entries}
        conflicts: list[KnowledgePackConflict] = []

        for entry in incoming_entries:
            current = merged.get(entry.canonical_id)
            if current is None:
                merged[entry.canonical_id] = deepcopy(entry)
                continue
            conflicts.append(
                KnowledgePackConflict(
                    canonical_id=entry.canonical_id,
                    existing_pack_id=existing_pack_id,
                    incoming_pack_id=incoming_pack_id,
                    resolution=resolution,
                )
            )
            if resolution == "prefer_incoming":
                merged[entry.canonical_id] = deepcopy(entry)

        return sorted(merged.values(), key=lambda item: item.canonical_id), conflicts
