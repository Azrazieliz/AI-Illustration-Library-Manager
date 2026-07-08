from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from engine.android.android_exceptions import AndroidSerializationError


@dataclass(slots=True)
class AndroidJob:
    job_id: str
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    checkpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AndroidJob":
        try:
            return cls(
                job_id=str(payload["job_id"]),
                status=str(payload.get("status", "pending")),
                progress=float(payload.get("progress", 0.0)),
                message=str(payload.get("message", "")),
                checkpoint=payload.get("checkpoint"),
                metadata=dict(payload.get("metadata", {})),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            raise AndroidSerializationError("Unable to deserialize AndroidJob") from exc


@dataclass(slots=True)
class AndroidImage:
    image_id: int
    path: str
    filename: str
    thumbnail_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AndroidImage":
        try:
            return cls(
                image_id=int(payload.get("image_id", 0)),
                path=str(payload["path"]),
                filename=str(payload.get("filename", "")),
                thumbnail_path=payload.get("thumbnail_path"),
                metadata=dict(payload.get("metadata", {})),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            raise AndroidSerializationError("Unable to deserialize AndroidImage") from exc


@dataclass(slots=True)
class AndroidSearchResult:
    image_id: int
    path: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AndroidSearchResult":
        try:
            return cls(
                image_id=int(payload.get("image_id", 0)),
                path=str(payload.get("path", "")),
                score=float(payload.get("score", 0.0)),
                metadata=dict(payload.get("metadata", {})),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            raise AndroidSerializationError("Unable to deserialize AndroidSearchResult") from exc


@dataclass(slots=True)
class AndroidCollection:
    collection_id: int
    name: str
    kind: str = "static"
    image_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AndroidCollection":
        try:
            return cls(
                collection_id=int(payload.get("collection_id", 0)),
                name=str(payload.get("name", "")),
                kind=str(payload.get("kind", "static")),
                image_count=int(payload.get("image_count", 0)),
                metadata=dict(payload.get("metadata", {})),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            raise AndroidSerializationError("Unable to deserialize AndroidCollection") from exc


@dataclass(slots=True)
class AndroidCharacter:
    character_id: int
    canonical_name: str
    series_id: int | None = None
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AndroidCharacter":
        try:
            return cls(
                character_id=int(payload.get("character_id", 0)),
                canonical_name=str(payload.get("canonical_name", "")),
                series_id=payload.get("series_id"),
                aliases=list(payload.get("aliases", [])),
                metadata=dict(payload.get("metadata", {})),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            raise AndroidSerializationError("Unable to deserialize AndroidCharacter") from exc


@dataclass(slots=True)
class AndroidSeries:
    series_id: int
    canonical_title: str
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AndroidSeries":
        try:
            return cls(
                series_id=int(payload.get("series_id", 0)),
                canonical_title=str(payload.get("canonical_title", "")),
                aliases=list(payload.get("aliases", [])),
                metadata=dict(payload.get("metadata", {})),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            raise AndroidSerializationError("Unable to deserialize AndroidSeries") from exc


@dataclass(slots=True)
class AndroidStatistics:
    bridge_calls: int = 0
    recognition_requests: int = 0
    searches: int = 0
    running_jobs: int = 0
    average_latency_ms: float = 0.0
    background_tasks: int = 0
    cache_usage_bytes: int = 0
    memory_usage_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AndroidStatistics":
        try:
            return cls(
                bridge_calls=int(payload.get("bridge_calls", 0)),
                recognition_requests=int(payload.get("recognition_requests", 0)),
                searches=int(payload.get("searches", 0)),
                running_jobs=int(payload.get("running_jobs", 0)),
                average_latency_ms=float(payload.get("average_latency_ms", 0.0)),
                background_tasks=int(payload.get("background_tasks", 0)),
                cache_usage_bytes=int(payload.get("cache_usage_bytes", 0)),
                memory_usage_bytes=int(payload.get("memory_usage_bytes", 0)),
            )
        except Exception as exc:  # pragma: no cover - defensive path
            raise AndroidSerializationError("Unable to deserialize AndroidStatistics") from exc


@dataclass(slots=True)
class AndroidSettings:
    json_serialization: bool = True
    parcelable_compatible: bool = True
    async_execution: bool = True
    streamed_progress_updates: bool = True
    future_jetpack_compose_ui: bool = True
    future_flutter_bridge: bool = True
    supported_android_versions: list[int] = field(default_factory=lambda: [11, 12, 13, 14, 15])
    scoped_storage_enabled: bool = True
    saf_enabled: bool = True
    media_store_enabled: bool = True
    document_provider_enabled: bool = True
    tree_uri_enabled: bool = True
    content_uri_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AndroidSettings":
        try:
            data = dict(payload)
            if "supported_android_versions" in data:
                data["supported_android_versions"] = [
                    int(item) for item in list(data.get("supported_android_versions", []))
                ]
            return cls(**data)
        except Exception as exc:  # pragma: no cover - defensive path
            raise AndroidSerializationError("Unable to deserialize AndroidSettings") from exc
