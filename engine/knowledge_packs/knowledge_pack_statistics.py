from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class KnowledgePackStatistics:
    installs: int = 0
    updates: int = 0
    uninstalls: int = 0
    rollbacks: int = 0
    merges: int = 0
    verify_calls: int = 0
    lookup_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    active_packs: int = 0
    total_installed_bytes: int = 0
    total_operation_latency_ms: float = 0.0

    @property
    def average_operation_latency_ms(self) -> float:
        total_ops = self.installs + self.updates + self.uninstalls + self.rollbacks + self.merges + self.verify_calls
        if total_ops <= 0:
            return 0.0
        return round(self.total_operation_latency_ms / float(total_ops), 6)

    def record_latency(self, milliseconds: float) -> None:
        self.total_operation_latency_ms += max(0.0, milliseconds)
