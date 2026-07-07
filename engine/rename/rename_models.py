from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


_PLACEHOLDER_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_ILLEGAL_FILENAME_CHARS = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_DUPLICATE_SPACES = re.compile(r"\s+")
_DUPLICATE_UNDERSCORES = re.compile(r"_+")

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


@dataclass(slots=True)
class RenameRule:
    """Configures template expansion and unknown placeholder defaults."""

    template: str = "{series}_{character}_{index}"
    unknown_defaults: dict[str, str] = field(
        default_factory=lambda: {
            "series": "unknown_series",
            "character": "unknown_character",
            "variant": "base",
            "artist_guess": "unknown_artist",
            "source": "unknown_source",
            "index": "000",
            "year": "0000",
        }
    )
    numbering_width: int = 3
    max_stem_length: int = 220


@dataclass(slots=True)
class RenameContext:
    """Resolved placeholder values for a source image."""

    image_id: int
    source_path: Path
    extension: str
    values: dict[str, str]


class RenameTemplate:
    """Expands placeholder-based templates into filename stems."""

    def __init__(self, template: str) -> None:
        self.template = template

    def expand(self, context: RenameContext, rule: RenameRule, *, sequence: int) -> str:
        merged = dict(rule.unknown_defaults)
        merged.update({key: value for key, value in context.values.items() if value})
        merged["index"] = str(sequence).zfill(rule.numbering_width)

        def replace(match: re.Match[str]) -> str:
            placeholder = match.group(1)
            return merged.get(placeholder, rule.unknown_defaults.get(placeholder, "unknown"))

        return _PLACEHOLDER_PATTERN.sub(replace, self.template)


@dataclass(slots=True)
class RenamePreview:
    """Single source-to-target rename preview item."""

    image_id: int
    source_path: Path
    target_path: Path
    sequence: int
    conflicted: bool = False
    skipped: bool = False
    reason: str | None = None


@dataclass(slots=True)
class RenameResult:
    """Result payload for preview/apply/rollback operations."""

    batch_id: str
    previews: list[RenamePreview]
    dry_run: bool
    applied: bool
    rolled_back: bool = False


@dataclass(slots=True)
class RenameBatchEntry:
    """Metadata for one applied rename used for rollback."""

    image_id: int
    source_path: Path
    target_path: Path


@dataclass(slots=True)
class RenameBatch:
    """Metadata for the most recently applied batch."""

    batch_id: str
    entries: list[RenameBatchEntry]
    applied_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def sanitize_stem(stem: str, *, max_length: int = 220) -> str:
    """Return a cross-platform safe filename stem."""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", stem)
    cleaned = _DUPLICATE_SPACES.sub(" ", cleaned)
    cleaned = _DUPLICATE_UNDERSCORES.sub("_", cleaned)
    cleaned = cleaned.strip().strip(".")

    if not cleaned:
        cleaned = "untitled"

    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_file"

    cleaned = cleaned[:max_length].strip().strip(".")
    return cleaned or "untitled"


def build_safe_filename(stem: str, extension: str, *, max_stem_length: int = 220) -> str:
    """Build a safe filename while preserving extension."""
    safe_stem = sanitize_stem(stem, max_length=max_stem_length)
    ext = extension if extension.startswith(".") else f".{extension}" if extension else ""
    return f"{safe_stem}{ext}"
