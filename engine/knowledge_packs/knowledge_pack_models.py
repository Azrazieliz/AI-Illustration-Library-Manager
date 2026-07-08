from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class KnowledgePackDomain(str, Enum):
    ANIME = "anime"
    MANGA = "manga"
    LIGHT_NOVEL = "light_novel"
    VISUAL_NOVEL = "visual_novel"
    GAME = "game"
    MANHWA = "manhwa"
    MANHUA = "manhua"
    ORIGINAL_CHARACTER = "original_character"
    CUSTOM = "custom"


class KnowledgePackCompression(str, Enum):
    NONE = "none"
    GZIP = "gzip"
    ZLIB = "zlib"
    LZMA = "lzma"


class KnowledgePackTaskType(str, Enum):
    INSTALL = "install"
    UPDATE = "update"
    UNINSTALL = "uninstall"
    ROLLBACK = "rollback"


class KnowledgePackTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(slots=True)
class KnowledgeRelationship:
    source_id: str
    target_id: str
    relation: str


@dataclass(slots=True)
class KnowledgeEntry:
    canonical_id: str
    canonical_name: str
    localized_names: dict[str, str] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    relationships: list[KnowledgeRelationship] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgePackManifest:
    pack_id: str
    version: str
    domain: KnowledgePackDomain
    author: str
    source: str
    checksum: str
    signature: str
    compression: KnowledgePackCompression = KnowledgePackCompression.GZIP
    metadata: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    priority: int = 0
    incremental_from: str | None = None
    installed_size_bytes: int = 0
    compressed_size_bytes: int = 0
    enabled: bool = True
    entries: list[KnowledgeEntry] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class KnowledgePackConflict:
    canonical_id: str
    existing_pack_id: str
    incoming_pack_id: str
    resolution: str


@dataclass(slots=True)
class KnowledgePackOperationResult:
    action: str
    pack_id: str
    success: bool
    message: str = ""
    conflicts: list[KnowledgePackConflict] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgePackLookupResult:
    canonical_id: str
    pack_id: str
    canonical_name: str
    localized_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgePackCheckpoint:
    job_id: str
    task_type: KnowledgePackTaskType
    status: KnowledgePackTaskStatus = KnowledgePackTaskStatus.PENDING
    stage: str = "queued"
    progress: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class KnowledgePackProgress:
    job_id: str
    task_type: KnowledgePackTaskType
    status: KnowledgePackTaskStatus
    progress: int
    message: str = ""
