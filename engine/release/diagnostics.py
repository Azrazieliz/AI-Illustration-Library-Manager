from __future__ import annotations

import gc
import os
import threading
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class RuntimeDiagnostics:
    collected_at_utc: str
    process_id: int
    working_directory: str
    active_threads: int
    gc_generation_counts: tuple[int, int, int]
    traced_memory_current_bytes: int
    traced_memory_peak_bytes: int


def collect_runtime_diagnostics() -> RuntimeDiagnostics:
    if not tracemalloc.is_tracing():
        tracemalloc.start()
    current, peak = tracemalloc.get_traced_memory()
    return RuntimeDiagnostics(
        collected_at_utc=datetime.now(timezone.utc).isoformat(),
        process_id=os.getpid(),
        working_directory=str(Path.cwd()),
        active_threads=threading.active_count(),
        gc_generation_counts=gc.get_count(),
        traced_memory_current_bytes=current,
        traced_memory_peak_bytes=peak,
    )
