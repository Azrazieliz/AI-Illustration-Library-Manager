from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class OrganizationRule:
    """One directory organization rule with priority and fallback support."""

    name: str
    directory_template: str
    priority: int = 100
    is_fallback: bool = False
    required_fields: tuple[str, ...] = field(default_factory=tuple)

    def can_apply(self, metadata: dict[str, str]) -> bool:
        if self.is_fallback:
            return True
        for field in self.required_fields:
            if not metadata.get(field):
                return False
        return True


@dataclass(slots=True)
class OrganizationPreview:
    """Single source-to-destination organization preview item."""

    image_id: int
    source_path: Path
    destination_path: Path
    rule_name: str
    sequence: int
    conflicted: bool = False
    skipped: bool = False
    reason: str | None = None


@dataclass(slots=True)
class OrganizationPlan:
    """Plan generated from rules before filesystem operations."""

    previews: list[OrganizationPreview]


@dataclass(slots=True)
class RollbackRecord:
    """Rollback metadata entry for one move operation."""

    image_id: int
    source_path: Path
    destination_path: Path


@dataclass(slots=True)
class OrganizationResult:
    """Result payload for organizer preview/apply/rollback operations."""

    batch_id: str
    previews: list[OrganizationPreview]
    dry_run: bool
    applied: bool
    rolled_back: bool = False


@dataclass(slots=True)
class RollbackBatch:
    """Metadata for one applied organization batch."""

    batch_id: str
    records: list[RollbackRecord]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
