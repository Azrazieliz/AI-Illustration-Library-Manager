from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time


@dataclass(slots=True)
class KnowledgeBaseStatistics:
    """Thread-safe aggregate statistics for knowledge-base activity."""

    datasets: int = 0
    characters: int = 0
    series: int = 0
    aliases: int = 0
    training_samples: int = 0
    reference_images: int = 0
    imports: int = 0
    exports: int = 0
    validation_runs: int = 0
    searches: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    elapsed_seconds: float = 0.0
    _start_time: float = 0.0
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def start(self) -> None:
        with self._lock:
            self._start_time = time()

    def finish(self) -> None:
        with self._lock:
            if self._start_time > 0:
                self.elapsed_seconds = time() - self._start_time

    def snapshot(self) -> "KnowledgeBaseStatistics":
        with self._lock:
            return KnowledgeBaseStatistics(
                datasets=self.datasets,
                characters=self.characters,
                series=self.series,
                aliases=self.aliases,
                training_samples=self.training_samples,
                reference_images=self.reference_images,
                imports=self.imports,
                exports=self.exports,
                validation_runs=self.validation_runs,
                searches=self.searches,
                cache_hits=self.cache_hits,
                cache_misses=self.cache_misses,
                elapsed_seconds=self.elapsed_seconds,
            )

    def apply_counts(
        self,
        *,
        datasets: int,
        characters: int,
        series: int,
        aliases: int,
        training_samples: int,
        reference_images: int,
    ) -> None:
        with self._lock:
            self.datasets = datasets
            self.characters = characters
            self.series = series
            self.aliases = aliases
            self.training_samples = training_samples
            self.reference_images = reference_images

    def increment_imports(self) -> None:
        with self._lock:
            self.imports += 1

    def increment_exports(self) -> None:
        with self._lock:
            self.exports += 1

    def increment_validation_runs(self) -> None:
        with self._lock:
            self.validation_runs += 1

    def increment_searches(self) -> None:
        with self._lock:
            self.searches += 1

    def increment_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def increment_cache_miss(self) -> None:
        with self._lock:
            self.cache_misses += 1
