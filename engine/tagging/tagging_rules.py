from __future__ import annotations

from collections import defaultdict

from engine.tagging.tagging_models import GeneratedTag, TagKind, TaggingContext


_EQUIVALENTS: dict[str, str] = {
    "jpg": "jpeg",
    "anime-art": "anime",
    "illustration": "artwork",
}


def generate_rule_based_tags(
    context: TaggingContext,
    *,
    suggested_threshold: float,
    inferred_threshold: float,
    confirmed_threshold: float,
) -> list[GeneratedTag]:
    """Generate and merge tags from all available evidence sources."""
    candidates: dict[str, GeneratedTag] = {}

    def add(name: str, confidence: float, provenance: str) -> None:
        normalized = _normalize_tag(name)
        if not normalized:
            return

        kind = _classify(confidence, suggested_threshold, inferred_threshold, confirmed_threshold)
        if kind is None:
            return

        existing = candidates.get(normalized)
        if existing is None:
            candidates[normalized] = GeneratedTag(
                name=normalized,
                confidence=confidence,
                kind=kind,
                provenance=[provenance],
            )
            return

        if confidence > existing.confidence:
            existing.confidence = confidence
            existing.kind = kind
        if provenance not in existing.provenance:
            existing.provenance.append(provenance)

    meta = context.metadata
    mime = meta.get("mime_type")
    if isinstance(mime, str):
        add(mime.split("/")[-1], 0.65, "metadata:mime_type")
    orientation = meta.get("orientation")
    if isinstance(orientation, str):
        add(orientation, 0.55, "metadata:orientation")
    color_mode = meta.get("color_mode")
    if isinstance(color_mode, str):
        add(color_mode.lower(), 0.58, "metadata:color_mode")
    is_animated = meta.get("is_animated")
    if is_animated is True:
        add("animated", 0.78, "metadata:is_animated")

    recognition = context.recognition
    series = recognition.get("series")
    if isinstance(series, str) and series.strip():
        add(series, 0.92, "recognition:series")

    characters = recognition.get("characters")
    if isinstance(characters, list):
        for name in characters:
            if isinstance(name, str) and name.strip():
                add(name, 0.9, "recognition:character")

    for neighbor in context.semantic_neighbors:
        neighbor_tags = neighbor.get("tags")
        similarity = neighbor.get("similarity", 0.0)
        if not isinstance(similarity, float):
            continue
        if isinstance(neighbor_tags, list):
            for tag in neighbor_tags:
                if isinstance(tag, str):
                    add(tag, min(0.88, 0.35 + similarity * 0.6), "semantic_neighbor")

    for relation in context.graph_neighbors:
        label = relation.get("label")
        if isinstance(label, str) and label.strip():
            add(label, 0.83, "knowledge_graph")

    add("auto-tagged", 0.7, "system")

    tags = list(candidates.values())
    tags.sort(key=lambda item: item.confidence, reverse=True)
    return tags


def _normalize_tag(tag: str) -> str:
    key = "-".join(tag.strip().lower().replace("_", " ").split())
    return _EQUIVALENTS.get(key, key)


def _classify(
    confidence: float,
    suggested_threshold: float,
    inferred_threshold: float,
    confirmed_threshold: float,
) -> TagKind | None:
    if confidence >= confirmed_threshold:
        return TagKind.CONFIRMED
    if confidence >= inferred_threshold:
        return TagKind.INFERRED
    if confidence >= suggested_threshold:
        return TagKind.SUGGESTED
    return None
