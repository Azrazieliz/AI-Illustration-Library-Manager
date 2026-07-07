from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from engine.knowledge_base.knowledge_base_builder import KnowledgeBaseBuilder
from engine.knowledge_base.knowledge_base_models import (
    KnowledgeBaseCandidate,
    KnowledgeBaseCheckpoint,
    KnowledgeBaseImportFormat,
    KnowledgeBaseOperationResult,
    KnowledgeBaseValidationReport,
)
from engine.knowledge_base.knowledge_base_statistics import KnowledgeBaseStatistics
from engine.logging import get_logger
from engine.repositories.knowledge_base_repository import KnowledgeBaseRepository


class KnowledgeBaseEngine:
    """Coordinates trusted knowledge-base operations and statistics."""

    def __init__(
        self,
        *,
        repository: KnowledgeBaseRepository | None = None,
        builder: KnowledgeBaseBuilder | None = None,
        callback: Callable[[object], None] | None = None,
    ) -> None:
        self.repository = repository or KnowledgeBaseRepository()
        self.builder = builder or self.repository.builder
        self.callback = callback
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = KnowledgeBaseStatistics()
        self._search_cache: dict[str, list[KnowledgeBaseCandidate]] = {}

    # ------------------------------------------------------------------
    # Creation helpers
    # ------------------------------------------------------------------
    def create_dataset(self, **kwargs: Any):
        dataset = self.repository.create_dataset(**kwargs)
        self._sync_statistics()
        self._search_cache.clear()
        return dataset

    def create_series(self, **kwargs: Any):
        series = self.repository.create_series(**kwargs)
        self._sync_statistics()
        self._search_cache.clear()
        return series

    def create_character(self, **kwargs: Any):
        character = self.repository.create_character(**kwargs)
        self._sync_statistics()
        self._search_cache.clear()
        return character

    def add_reference_image(self, **kwargs: Any):
        reference = self.repository.add_reference_image(**kwargs)
        self._sync_statistics()
        self._search_cache.clear()
        return reference

    def add_training_sample(self, **kwargs: Any):
        sample = self.repository.add_training_sample(**kwargs)
        self._sync_statistics()
        self._search_cache.clear()
        return sample

    def add_approved_review_sample(self, review_item, **kwargs: Any):
        sample = self.repository.add_approved_review_sample(review_item, **kwargs)
        self._sync_statistics()
        self._search_cache.clear()
        return sample

    def promote_trusted_sample(self, sample_id: int):
        sample = self.repository.promote_trusted_sample(sample_id)
        self._sync_statistics()
        return sample

    def reject_training_sample(self, sample_id: int):
        sample = self.repository.reject_training_sample(sample_id)
        self._sync_statistics()
        return sample

    # ------------------------------------------------------------------
    # Search helpers
    # ------------------------------------------------------------------
    def lookup_candidates(self, query: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._cached_search("lookup_candidates", query, dataset_id=dataset_id, limit=limit, mode="all")

    def lookup_by_alias(self, alias: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._cached_search("lookup_by_alias", alias, dataset_id=dataset_id, limit=limit, mode="alias")

    def lookup_by_series(self, series: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._cached_search("lookup_by_series", series, dataset_id=dataset_id, limit=limit, mode="series")

    def lookup_by_character(self, character: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._cached_search("lookup_by_character", character, dataset_id=dataset_id, limit=limit, mode="character")

    def lookup_by_localized_name(self, name: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._cached_search("lookup_by_localized_name", name, dataset_id=dataset_id, limit=limit, mode="localized")

    def lookup_by_romaji(self, name: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._cached_search("lookup_by_romaji", name, dataset_id=dataset_id, limit=limit, mode="romaji")

    def search_tags(self, query: str, *, dataset_id: int | None = None, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._cached_search("search_tags", query, dataset_id=dataset_id, limit=limit, mode="tags")

    def search_datasets(self, query: str, *, limit: int = 10) -> list[KnowledgeBaseCandidate]:
        return self._cached_search("search_datasets", query, dataset_id=None, limit=limit, mode="datasets")

    def lookup_by_canonical_id(self, identifier: int, *, dataset_id: int | None = None) -> list[KnowledgeBaseCandidate]:
        self.statistics.increment_searches()
        results = self.repository.lookup_by_canonical_id(identifier, dataset_id=dataset_id)
        self.statistics.increment_cache_miss()
        return results

    # ------------------------------------------------------------------
    # Import/export and validation
    # ------------------------------------------------------------------
    def import_dataset(
        self,
        data: str | dict[str, Any],
        *,
        format: KnowledgeBaseImportFormat | str = KnowledgeBaseImportFormat.JSON,
        merge: bool = False,
    ):
        dataset = self.repository.import_dataset(data, format=format, merge=merge)
        self.statistics.increment_imports()
        self._sync_statistics()
        self._search_cache.clear()
        self._emit({"action": "import", "dataset_id": dataset.dataset_id})
        return dataset

    def export_dataset(self, dataset_id: int, *, format: KnowledgeBaseImportFormat | str = KnowledgeBaseImportFormat.JSON):
        payload = self.repository.export_dataset(dataset_id, format=format)
        self.statistics.increment_exports()
        self._emit({"action": "export", "dataset_id": dataset_id})
        return payload

    def validate(self, dataset_id: int | None = None) -> KnowledgeBaseValidationReport:
        self.statistics.increment_validation_runs()
        report = self.repository.validate(dataset_id=dataset_id)
        self._emit({"action": "validate", "valid": report.valid})
        return report

    def rebuild_statistics(self) -> KnowledgeBaseStatistics:
        self._sync_statistics()
        return self.statistics.snapshot()

    def merge_datasets(self, target_dataset_id: int, source_dataset_id: int):
        dataset = self.repository.merge_datasets(target_dataset_id, source_dataset_id)
        self._sync_statistics()
        self._search_cache.clear()
        return dataset

    def import_bundle(self, bundle: dict[str, Any], *, merge: bool = False):
        dataset = self.repository.import_bundle(bundle, merge=merge)
        self.statistics.increment_imports()
        self._sync_statistics()
        self._search_cache.clear()
        self._emit({"action": "import", "dataset_id": dataset.dataset_id})
        return dataset

    def counts(self, dataset_id: int | None = None) -> dict[str, int]:
        return self.repository.counts(dataset_id)

    def statistics_snapshot(self) -> KnowledgeBaseStatistics:
        return self.statistics.snapshot()

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: KnowledgeBaseCheckpoint | None = None,
    ) -> list[KnowledgeBaseOperationResult]:
        results: list[KnowledgeBaseOperationResult] = []
        for path in paths:
            result = self.import_dataset(Path(path).read_text(encoding="utf-8"), format=KnowledgeBaseImportFormat.JSON)
            results.append(
                self.builder.build_operation_result(
                    action=self._infer_action_from_path(path),
                    success=True,
                    message="Imported knowledge-base payload.",
                    dataset_id=result.dataset_id,
                )
            )
            if checkpoint is not None:
                checkpoint.add_processed(str(path))
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _cached_search(self, label: str, query: str, *, dataset_id: int | None, limit: int, mode: str) -> list[KnowledgeBaseCandidate]:
        cache_key = f"{label}|{mode}|{dataset_id or '*'}|{limit}|{self.builder.normalize_text(query)}"
        self.statistics.increment_searches()
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            self.statistics.increment_cache_hit()
            return [item for item in cached[:limit]]

        self.statistics.increment_cache_miss()
        if mode == "alias":
            results = self.repository.lookup_by_alias(query, dataset_id=dataset_id, limit=limit)
        elif mode == "series":
            results = self.repository.lookup_by_series(query, dataset_id=dataset_id, limit=limit)
        elif mode == "character":
            results = self.repository.lookup_by_character(query, dataset_id=dataset_id, limit=limit)
        elif mode == "localized":
            results = self.repository.lookup_by_localized_name(query, dataset_id=dataset_id, limit=limit)
        elif mode == "romaji":
            results = self.repository.lookup_by_romaji(query, dataset_id=dataset_id, limit=limit)
        elif mode == "tags":
            results = self.repository.search_tags(query, dataset_id=dataset_id, limit=limit)
        elif mode == "datasets":
            results = self.repository.search_datasets(query, limit=limit)
        elif mode == "all":
            results = self.repository.lookup_candidates(query, dataset_id=dataset_id, limit=limit)
        else:
            results = self.repository.lookup_candidates(query, dataset_id=dataset_id, limit=limit)
        self._search_cache[cache_key] = [item for item in results]
        return results

    def _sync_statistics(self) -> None:
        counts = self.repository.counts()
        self.statistics.apply_counts(
            datasets=counts["datasets"],
            characters=counts["characters"],
            series=counts["series"],
            aliases=counts["aliases"],
            training_samples=counts["training_samples"],
            reference_images=counts["reference_images"],
        )

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)

    @staticmethod
    def _infer_action_from_path(path: Path | str) -> KnowledgeBaseTaskType:
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            return KnowledgeBaseTaskType.IMPORT
        return KnowledgeBaseTaskType.IMPORT
