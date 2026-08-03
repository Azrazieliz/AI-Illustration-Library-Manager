from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config) -> None:
    """Use a per-process basetemp to avoid cross-run sqlite file locking on Windows."""
    pid = os.getpid()
    base = Path.cwd() / "pytest_tmp" / f"pid-{pid}"
    base.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(base)
