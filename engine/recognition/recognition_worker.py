from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from engine.database import UnitOfWork
from engine.logging import get_logger
from engine.recognition.recognition_events import (
    RecognitionCompletedForPath,
    RecognitionFailed,
    RecognitionSkipped,
    RecognitionStarted,
)
from engine.recognition.recognition_exceptions import RecognitionProviderError
from engine.recognition.recognition_matcher import RecognitionMatcher
from engine.recognition.recognition_models import (
    RecognitionCache,
    RecognitionCheckpoint,
    RecognitionOutput,
    RecognitionResult,
)
from engine.recognition.recognition_provider import RecognitionProvider
from engine.recognition.recognition_statistics import RecognitionStatistics
from engine.repositories.recognition_repository import RecognitionRepository


class RecognitionWorker:
    """Parallel recognition worker using per-thread repository instances."""

    def __init__(
        self,
        *,
        provider: RecognitionProvider,
        recognition_repository: RecognitionRepository | None = None,
        matcher: RecognitionMatcher | None = None,
        cache: RecognitionCache | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.provider = provider
        self.recognition_repository = recognition_repository or RecognitionRepository()
        self.matcher = matcher
        self.cache = cache or RecognitionCache()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = RecognitionStatistics()

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: RecognitionCheckpoint | None = None,
    ) -> list[RecognitionResult]:
        """Process recognition for multiple paths in parallel."""
        self.statistics = RecognitionStatistics()
        self.statistics.start()
        results: list[RecognitionResult] = []
        resolved_paths = [str(Path(p).resolve()) for p in paths]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_one, path, checkpoint): path
                for path in resolved_paths
            }

            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    results.append(result)

        self.statistics.finish()
        return results

    def process_path(
        self,
        path: Path | str,
        *,
        checkpoint: RecognitionCheckpoint | None = None,
    ) -> RecognitionResult | None:
        """Process recognition for a single path."""
        return self._process_one(str(Path(path).resolve()), checkpoint)

    def _process_one(
        self,
        path: str,
        checkpoint: RecognitionCheckpoint | None,
    ) -> RecognitionResult | None:
        """Process one image path with thread-local repositories."""
        resolved_path = Path(path)

        if checkpoint is not None and checkpoint.is_processed(path):
            self.statistics.increment_processed()
            self.statistics.increment_skipped()
            self._emit(RecognitionSkipped(path=resolved_path, reason="Already processed"))
            return None

        try:
            with UnitOfWork() as session:
                repository = RecognitionRepository(session=session)
                self.statistics.increment_processed()
                self._emit(RecognitionStarted(path=resolved_path))

                image = repository.get_image_by_path(path)
                if image is None:
                    self.statistics.increment_skipped()
                    self._emit(RecognitionSkipped(path=resolved_path, reason="Image not in database"))
                    return None

                cache_key = self._build_cache_key(resolved_path=resolved_path, image_id=image.id)
                output = self.cache.get(cache_key)
                if output is not None:
                    self.statistics.increment_cache_hit()
                else:
                    self.statistics.increment_cache_miss()
                    output = self.provider.recognize(resolved_path)
                    self.cache.put(cache_key, output)

                if output.series is None and not output.character_candidates and not output.characters:
                    self.statistics.increment_skipped()
                    self._emit(RecognitionSkipped(path=resolved_path, reason="No labels recognized"))
                    return None

                if self.matcher is not None:
                    match = self.matcher.match(image=image, output=output, path=resolved_path)
                    if match.cache_hit:
                        self.statistics.increment_cache_hit()
                    assignment = match.assignment
                    if assignment.auto_assigned:
                        series, characters = repository.apply_assignment(image=image, assignment=assignment, commit=False)
                    else:
                        series, characters = repository.apply_recognition(
                            image=image,
                            series_name=assignment.series_name or (output.series.name if output.series is not None else None),
                            character_names=output.ranked_character_names(),
                            commit=False,
                        )
                    output.assigned_character_id = assignment.character_id
                    output.assigned_series_id = assignment.series_id
                    output.assignment_confidence = assignment.confidence
                    output.requires_review = assignment.needs_review
                    output.candidate_payloads = list(assignment.candidates)
                    assignment_review_item_id = assignment.review_item_id
                    auto_assigned = assignment.auto_assigned
                    needs_review = assignment.needs_review
                    matched_candidates = list(assignment.candidates)
                    matching_seconds = match.matching_time_seconds
                    ranking_seconds = match.ranking_time_seconds
                    unknown_result = assignment.character_id is None
                else:
                    series_name = output.series.name if output.series is not None else None
                    character_names = output.ranked_character_names()

                    series, characters = repository.apply_recognition(
                        image=image,
                        series_name=series_name,
                        character_names=character_names,
                        commit=False,
                    )
                    assignment_review_item_id = None
                    auto_assigned = True
                    needs_review = False
                    matched_candidates = []
                    matching_seconds = 0.0
                    ranking_seconds = 0.0
                    unknown_result = False

                if checkpoint is not None:
                    checkpoint.add_processed(path)

                self.statistics.increment_recognized()
                if auto_assigned:
                    self.statistics.increment_automatic_assignment()
                if needs_review:
                    self.statistics.increment_review_submission()
                if unknown_result:
                    self.statistics.increment_unknown_result()
                self.statistics.add_candidates_ranked(len(output.character_candidates))
                self.statistics.record_confidence(output.overall_confidence)
                self.statistics.add_matching_time(matching_seconds)
                self.statistics.add_ranking_time(ranking_seconds)
                self._emit(
                    RecognitionCompletedForPath(
                        path=resolved_path,
                        image_id=image.id,
                        series=series.name if series is not None else None,
                        character_count=len(characters),
                    )
                )
                return RecognitionResult(
                    image_id=image.id,
                    path=resolved_path,
                    output=output,
                    assignment=assignment if self.matcher is not None else None,
                    review_item_id=assignment_review_item_id,
                    auto_assigned=auto_assigned,
                    needs_review=needs_review,
                    matched_candidates=matched_candidates,
                )

        except RecognitionProviderError as e:
            self.statistics.increment_failed()
            self._emit(RecognitionFailed(path=resolved_path, error=str(e)))
            return None
        except Exception as e:
            self.statistics.increment_failed()
            self._emit(RecognitionFailed(path=resolved_path, error=f"Unexpected error: {e}"))
            return None

    def _emit(self, event: object) -> None:
        if self.callback is not None:
            self.callback(event)

    def _build_cache_key(self, *, resolved_path: Path, image_id: int) -> str:
        return "|".join(
            [
                str(image_id),
                str(resolved_path),
                self.provider.get_provider_name(),
                self.provider.model_name,
                self.provider.model_version,
            ]
        )
