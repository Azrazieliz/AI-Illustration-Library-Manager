from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from engine.config import settings


@dataclass(slots=True)
class ReleaseMetadata:
    app_name: str
    version: str
    release_channel: str
    build_timestamp_utc: str
    build_commit: str
    python_version: str
    platform: str


def load_release_metadata() -> ReleaseMetadata:
    return ReleaseMetadata(
        app_name=settings.app_name,
        version=settings.version,
        release_channel=os.getenv("AILM_RELEASE_CHANNEL", "stable"),
        build_timestamp_utc=os.getenv("AILM_BUILD_TIMESTAMP", datetime.now(timezone.utc).isoformat()),
        build_commit=os.getenv("AILM_BUILD_COMMIT", "unknown"),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
    )
