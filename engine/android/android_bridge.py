from __future__ import annotations

from time import perf_counter
from typing import Any

from engine.android.android_models import AndroidCharacter, AndroidCollection, AndroidImage, AndroidJob, AndroidSearchResult
from engine.android.android_service import AndroidService


class AndroidBridge:
    """Android-facing API layer that delegates to the adapter service."""

    def __init__(self, *, service: AndroidService | None = None) -> None:
        self.service = service or AndroidService()

    def scanLibrary(self, root: str) -> list[AndroidImage]:
        return self._timed_call(self.service.scan_library, root)

    def recognizeImage(self, path: str) -> dict[str, Any] | None:
        return self._timed_call(self.service.recognize_image, path)

    def renameImage(self, path: str, *, dry_run: bool = False, rule: Any | None = None) -> Any:
        return self._timed_call(self.service.rename_image, path, dry_run=dry_run, rule=rule)

    def organizeImage(self, path: str, *, dry_run: bool = False, rules: list[Any] | None = None) -> Any:
        return self._timed_call(self.service.organize_image, path, dry_run=dry_run, rules=rules)

    def search(self, *, query_vector: list[float], top_k: int = 10, min_similarity: float = 0.0) -> list[AndroidSearchResult]:
        return self._timed_call(self.service.search, query_vector=query_vector, top_k=top_k, min_similarity=min_similarity)

    def advancedSearch(self, *, action: str = "search", payload: dict[str, Any] | None = None) -> Any:
        return self._timed_call(self.service.advanced_search, action=action, payload=payload)

    def semanticSearch(self, *, query_vector: list[float], top_k: int = 10, min_similarity: float = 0.0) -> list[AndroidSearchResult]:
        return self._timed_call(self.service.semantic_search, query_vector=query_vector, top_k=top_k, min_similarity=min_similarity)

    def getCollections(self, *, query: str | None = None, page: int = 1, page_size: int = 50) -> list[AndroidCollection]:
        return self._timed_call(self.service.get_collections, query=query, page=page, page_size=page_size)

    def getCharacter(self, identifier: int | str) -> AndroidCharacter | None:
        return self._timed_call(self.service.get_character, identifier)

    def getSeries(self, identifier: int | str):
        return self._timed_call(self.service.get_series, identifier)

    def getTags(self) -> list[str]:
        return self._timed_call(self.service.get_tags)

    def startBulkOperation(self, operation: str, **kwargs: Any) -> AndroidJob:
        return self._timed_call(self.service.start_bulk_operation, operation, **kwargs)

    def getJobs(self) -> list[AndroidJob]:
        return self._timed_call(self.service.get_jobs)

    def cancelJob(self, job_id: str) -> bool:
        return self._timed_call(self.service.cancel_job, job_id)

    def resumeJob(self, job_id: str) -> bool:
        return self._timed_call(self.service.resume_job, job_id)

    def pauseAutomation(self, job_id: str | None = None) -> Any:
        return self._timed_call(self.service.pause_automation, job_id)

    def resumeAutomation(self, job_id: str | None = None) -> Any:
        return self._timed_call(self.service.resume_automation, job_id)

    def exportDataset(self, source_path: str, *, metadata: dict[str, Any] | None = None) -> Any:
        return self._timed_call(self.service.export_dataset, source_path, metadata=metadata)

    def libraryStatistics(self) -> dict[str, Any]:
        return self._timed_call(self.service.library_statistics)

    def healthStatus(self) -> dict[str, Any]:
        return self._timed_call(self.service.health_status)

    def _timed_call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        result = func(*args, **kwargs)
        elapsed_ms = (perf_counter() - started) * 1000.0
        self.service.statistics.record_bridge_call(elapsed_ms)
        return result
