from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from engine.knowledge_graph import EdgeType, KnowledgeGraphEngine
from engine.logging import get_logger
from engine.repositories.tagging_repository import TaggingRepository
from engine.tagging.tagging_backend import RuleBasedTaggingBackend, TaggingBackend
from engine.tagging.tagging_events import (
    TaggingCompleted,
    TaggingFailed,
    TaggingGenerated,
    TaggingSkipped,
    TaggingStarted,
)
from engine.tagging.tagging_models import TagKind, TaggingCheckpoint, TaggingContext, TaggingResult
from engine.tagging.tagging_statistics import TaggingStatistics


class TaggingEngine:
    """Orchestrates automatic tag generation and persistence."""

    def __init__(
        self,
        *,
        repository: TaggingRepository | None = None,
        backend: TaggingBackend | None = None,
        knowledge_graph_engine: KnowledgeGraphEngine | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
        suggested_threshold: float = 0.5,
        inferred_threshold: float = 0.7,
        confirmed_threshold: float = 0.9,
        top_k_neighbors: int = 5,
    ) -> None:
        self.repository = repository or TaggingRepository()
        self.backend = backend or RuleBasedTaggingBackend()
        self.knowledge_graph_engine = knowledge_graph_engine or KnowledgeGraphEngine()
        self.callback = callback
        self.max_workers = max_workers
        self.suggested_threshold = suggested_threshold
        self.inferred_threshold = inferred_threshold
        self.confirmed_threshold = confirmed_threshold
        self.top_k_neighbors = top_k_neighbors
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = TaggingStatistics()

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: TaggingCheckpoint | None = None,
        metadata: dict | None = None,
    ) -> list[TaggingResult]:
        """Generate and persist automatic tags for multiple paths in parallel."""
        self.statistics = TaggingStatistics()
        self.statistics.start()
        results: list[TaggingResult] = []
        resolved_paths = [str(Path(path).resolve()) for path in paths]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_one, path, checkpoint, metadata): path
                for path in resolved_paths
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)

        self.statistics.finish()
        self._emit(
            TaggingCompleted(
                total=self.statistics.processed,
                tagged=self.statistics.tagged,
                skipped=self.statistics.skipped,
                failed=self.statistics.failed,
            )
        )
        return results

    def process_path(
        self,
        path: Path | str,
        *,
        checkpoint: TaggingCheckpoint | None = None,
        metadata: dict | None = None,
    ) -> TaggingResult | None:
        """Generate and persist automatic tags for one path."""
        return self._process_one(str(Path(path).resolve()), checkpoint, metadata)

    def _process_one(
        self,
        path: str,
        checkpoint: TaggingCheckpoint | None,
        metadata: dict | None,
    ) -> TaggingResult | None:
        resolved = Path(path)

        if checkpoint is not None and checkpoint.is_processed(path):
            self.statistics.increment_processed()
            self.statistics.increment_skipped()
            self._emit(TaggingSkipped(path=resolved, reason="Already processed"))
            return None

        self.statistics.increment_processed()
        self._emit(TaggingStarted(path=resolved))

        try:
            repository = TaggingRepository()
            image = repository.get_image_by_path(path)
            if image is None:
                self.statistics.increment_skipped()
                self._emit(TaggingSkipped(path=resolved, reason="Image not found"))
                return None

            metadata_record = repository.get_metadata_by_image_id(image.id)
            metadata_payload = {
                "mime_type": metadata_record.mime_type if metadata_record else None,
                "orientation": metadata_record.orientation if metadata_record else None,
                "color_mode": metadata_record.color_mode if metadata_record else None,
                "is_animated": metadata_record.is_animated if metadata_record else False,
            }

            recognition_payload = {
                "series": (metadata or {}).get("series"),
                "characters": [
                    item.get("name")
                    for item in (metadata or {}).get("characters", [])
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                ],
            }

            semantic_neighbors = self._semantic_neighbors(repository, image.id)
            graph_neighbors = self._graph_neighbors(image.id)

            context = TaggingContext(
                image_id=image.id,
                path=resolved,
                metadata=metadata_payload,
                recognition=recognition_payload,
                semantic_neighbors=semantic_neighbors,
                graph_neighbors=graph_neighbors,
            )

            tags = self.backend.generate_tags(
                context,
                suggested_threshold=self.suggested_threshold,
                inferred_threshold=self.inferred_threshold,
                confirmed_threshold=self.confirmed_threshold,
            )

            if not tags:
                self.statistics.increment_skipped()
                self._emit(TaggingSkipped(path=resolved, reason="No tags generated"))
                return None

            existing = {tag.name.lower() for tag in image.tags}
            for generated in tags:
                if generated.name.lower() in existing:
                    # Incremental re-tagging keeps duplicates out while updating provenance.
                    repository.save_provenance(
                        image_id=image.id,
                        tag_name=generated.name,
                        provenance=generated.provenance,
                    )
                    continue

                category = generated.kind.value
                tag = repository.get_or_create_tag(name=generated.name, category=category)
                repository.assign_tag(image, tag)
                repository.save_provenance(
                    image_id=image.id,
                    tag_name=generated.name,
                    provenance=generated.provenance,
                )
                existing.add(generated.name.lower())

            repository.commit_changes()

            if checkpoint is not None:
                checkpoint.add_processed(path)

            self.statistics.increment_tagged()
            self._emit(TaggingGenerated(path=resolved, image_id=image.id, tag_count=len(tags)))
            return TaggingResult(image_id=image.id, path=resolved, generated_tags=tags)

        except Exception as e:
            self.statistics.increment_failed()
            self._emit(TaggingFailed(path=resolved, error=str(e)))
            return None

    def _semantic_neighbors(self, repository: TaggingRepository, image_id: int) -> list[dict[str, object]]:
        embedding = repository.get_embedding_by_image_id(image_id)
        if embedding is None:
            return []

        query_vector = _vector_from_path(embedding.vector_path)
        candidates = []
        for row in repository.list_all_embeddings():
            if row.image_id == image_id:
                continue
            candidate_vector = _vector_from_path(row.vector_path)
            similarity = _cosine_similarity(query_vector, candidate_vector)
            img = repository.get_by_id(row.image_id)
            tag_names = [tag.name for tag in img.tags] if img is not None else []
            candidates.append(
                {
                    "image_id": row.image_id,
                    "similarity": similarity,
                    "tags": tag_names,
                }
            )

        candidates.sort(key=lambda item: float(item["similarity"]), reverse=True)
        return candidates[: self.top_k_neighbors]

    def _graph_neighbors(self, image_id: int) -> list[dict[str, object]]:
        image_node_id = f"image:{image_id}"
        neighbors = self.knowledge_graph_engine.neighbors(image_node_id)
        return [{"id": node.id, "label": node.label, "type": node.node_type.value} for node in neighbors]

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)


def _vector_from_path(vector_path: str) -> list[float]:
    seed = vector_path.encode("utf-8")
    values: list[float] = []
    while len(values) < 128:
        for byte in seed:
            values.append(float(byte) / 255.0)
            if len(values) >= 128:
                break
    return values


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = sum(x * x for x in left) ** 0.5
    right_norm = sum(x * x for x in right) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(left, right))
    return dot / (left_norm * right_norm)
