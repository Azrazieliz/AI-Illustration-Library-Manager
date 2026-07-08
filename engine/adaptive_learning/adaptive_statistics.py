from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AdaptiveLearningStatistics:
    learning_iterations: int = 0
    accepted_samples: int = 0
    rejected_samples: int = 0
    precision_improvement: float = 0.0
    recall_improvement: float = 0.0
    confidence_evolution: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    training_duration_seconds: float = 0.0
    active_profiles: int = 0
    uncertainty_queue_size: int = 0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total <= 0:
            return 0.0
        return round(self.cache_hits / float(total), 6)
