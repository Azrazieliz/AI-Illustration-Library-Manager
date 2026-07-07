from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.logging import get_logger


class EmbeddingCache:
    """In-memory cache for embeddings with optional disk persistence."""

    def __init__(self, cache_dir: Path | str | None = None, max_size: int = 10000) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_size = max_size
        self._cache: dict[int, dict[str, Any]] = {}
        self.logger = get_logger(self.__class__.__name__)

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, image_id: int, model_name: str) -> list[float] | None:
        """Retrieve embedding from cache."""
        cache_key = self._make_key(image_id, model_name)

        # Check memory cache
        if cache_key in self._cache:
            return self._cache[cache_key].get("vector")

        # Check disk cache
        if self.cache_dir:
            disk_cache_file = self._get_cache_file(image_id, model_name)
            if disk_cache_file.exists():
                try:
                    with open(disk_cache_file) as f:
                        data = json.load(f)
                    vector = data.get("vector")
                    # Load into memory
                    self._cache[cache_key] = data
                    return vector
                except Exception as e:
                    self.logger.warning(f"Failed to load disk cache: {e}")

        return None

    def put(self, image_id: int, model_name: str, vector: list[float]) -> None:
        """Store embedding in cache."""
        cache_key = self._make_key(image_id, model_name)

        data = {
            "image_id": image_id,
            "model_name": model_name,
            "vector": vector,
        }

        # Store in memory
        if len(self._cache) >= self.max_size:
            # Simple eviction: remove first item
            self._cache.pop(next(iter(self._cache)))

        self._cache[cache_key] = data

        # Store on disk
        if self.cache_dir:
            try:
                disk_cache_file = self._get_cache_file(image_id, model_name)
                disk_cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(disk_cache_file, "w") as f:
                    json.dump(data, f)
            except Exception as e:
                self.logger.warning(f"Failed to save disk cache: {e}")

    def clear(self) -> None:
        """Clear in-memory cache."""
        self._cache.clear()

    def _make_key(self, image_id: int, model_name: str) -> str:
        """Create cache key from image_id and model_name."""
        return f"{image_id}:{model_name}"

    def _get_cache_file(self, image_id: int, model_name: str) -> Path:
        """Get disk cache file path."""
        # Use model_name as subdirectory to organize by model
        safe_model_name = model_name.replace("/", "_")
        return self.cache_dir / safe_model_name / f"{image_id}.json"
