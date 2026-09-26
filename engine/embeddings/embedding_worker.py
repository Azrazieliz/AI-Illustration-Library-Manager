from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterable
from uuid import uuid4

import numpy as np

from engine.embeddings.embedding_cache import EmbeddingCache
from engine.embeddings.embedding_events import (
    EmbeddingExtracted,
    EmbeddingFailed,
    EmbeddingSkipped,
    EmbeddingStarted,
)
from engine.embeddings.embedding_exceptions import ProviderError
from engine.embeddings.embedding_models import (
    EmbeddingCheckpoint,
    EmbeddingResult,
    ExtractedEmbedding,
)
from engine.embeddings.embedding_provider import EmbeddingProvider
from engine.embeddings.embedding_statistics import EmbeddingStatistics
from engine.logging import get_logger
from engine.repositories.ai_execution_repository import AiExecutionRepository
from engine.repositories.embedding_repository import EmbeddingRepository
from engine.repositories.image_repository import ImageRepository


class EmbeddingWorker:
    """Parallel embedding generation worker with per-thread repositories."""

    def __init__(
        self,
        *,
        provider: EmbeddingProvider,
        image_repository: ImageRepository | None = None,
        embedding_repository: EmbeddingRepository | None = None,
        cache: EmbeddingCache | None = None,
        callback: Callable[[object], None] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.provider = provider
        self.image_repository = image_repository or ImageRepository()
        self.embedding_repository = embedding_repository or EmbeddingRepository()
        self.cache = cache or EmbeddingCache()
        self.callback = callback
        self.max_workers = max_workers
        self.logger = get_logger(self.__class__.__name__)
        self.statistics = EmbeddingStatistics()

    def process_paths(
        self,
        paths: Iterable[Path | str],
        *,
        checkpoint: EmbeddingCheckpoint | None = None,
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple paths in parallel."""
        self.statistics.start()
        paths_list = [Path(p) for p in paths]
        results: list[EmbeddingResult] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_one, path, checkpoint): path
                for path in paths_list
            }

            for future in as_completed(futures):
                path = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        results.append(result)
                        self.statistics.embedded += 1
                except Exception as e:
                    self.logger.error(f"Embedding extraction failed for {path}: {e}")
                    self.statistics.failed += 1

        self.statistics.processed = len(paths_list)
        self.statistics.finish()
        return results

    def _process_one(
        self,
        path: Path | str,
        checkpoint: EmbeddingCheckpoint | None = None,
    ) -> EmbeddingResult | None:
        """Generate embedding for a single image (runs in worker thread)."""
        path = Path(path)

        # Check checkpoint
        if checkpoint and checkpoint.is_processed(path):
            self.statistics.skipped += 1
            self._emit(EmbeddingSkipped(path=path, reason="Already processed"))
            return None

        # Create fresh repositories for this thread
        image_repository = ImageRepository()
        embedding_repository = EmbeddingRepository()

        try:
            # Get image record
            image = image_repository.get_by_path(str(path))
            if image is None:
                self.statistics.skipped += 1
                self._emit(
                    EmbeddingSkipped(path=path, reason="Image not in database")
                )
                return None

            # Check if embedding already exists in database
            existing_embedding = embedding_repository.get_by_image_id(image.id)
            if existing_embedding is not None:
                if (
                    existing_embedding.model_name == self.provider.model_name
                    and Path(existing_embedding.vector_path).is_file()
                ):
                    self.statistics.skipped += 1
                    self._emit(EmbeddingSkipped(path=path, reason="Embedding already exists"))
                    return None

            # Generate embedding
            self._emit(EmbeddingStarted(path=path, model_name=self.provider.model_name))

            cached_vector = self.cache.get(image.id, self.provider.model_name)
            if cached_vector is not None:
                embedding = ExtractedEmbedding(
                    image_id=image.id,
                    embedding_vector=cached_vector,
                    model_name=self.provider.model_name,
                    model_version=self.provider.model_version,
                    dimensions=len(cached_vector),
                    provider_name=self.provider.get_provider_name(),
                )
            else:
                try:
                    execution_started = perf_counter()
                    embedding = self.provider.extract_embedding(image.id, path)
                    execution_duration = perf_counter() - execution_started
                except ProviderError as e:
                    self.statistics.failed += 1
                    self._emit(EmbeddingFailed(path=path, error=str(e)))
                    return None

            # Persist to database
            vector_path = self._save_embedding_vector(embedding)
            
            # Use existing record or create new one
            if existing_embedding is not None:
                embedding_record = embedding_repository.update_embedding_record(
                    existing_embedding,
                    vector_path=str(vector_path),
                    model_name=embedding.model_name,
                    model_version=embedding.model_version,
                )
            else:
                embedding_record = embedding_repository.create_embedding_record(
                    image_id=image.id,
                    vector_path=str(vector_path),
                    model_name=embedding.model_name,
                    model_version=embedding.model_version,
                )
            if cached_vector is None:
                AiExecutionRepository(session=embedding_repository.session).append(
                    task="embedding_generation",
                    model=embedding.model_name,
                    model_version=embedding.model_version,
                    runtime=embedding.provider_name,
                    input_hash=AiExecutionRepository.hash_file(path),
                    output_hash=embedding_record.checksum,
                    duration=execution_duration,
                    status="completed",
                )
            embedding_repository.commit()

            # Update cache
            self.cache.put(image.id, self.provider.model_name, embedding.embedding_vector)

            # Update image record
            image_repository.mark_embedding_created(image)
            image_repository.commit()

            # Update checkpoint
            if checkpoint:
                checkpoint.add_processed(path)

            self._emit(
                EmbeddingExtracted(
                    path=path,
                    dimensions=embedding.dimensions,
                    model_name=embedding.model_name,
                )
            )

            result = EmbeddingResult(
                image_id=image.id,
                path=path,
                embedding=embedding,
                extracted_at=embedding_record.created_at,
            )
            return result

        except Exception as e:
            self.logger.error(f"Unexpected error processing {path}: {e}")
            self.statistics.failed += 1
            self._emit(EmbeddingFailed(path=path, error=str(e)))
            return None

    def _save_embedding_vector(self, embedding) -> Path:
        """Persist one validated embedding vector as a NumPy artifact."""
        from engine.config import settings

        embeddings_dir = settings.embedding_directory
        embeddings_dir_path = Path(embeddings_dir) if not isinstance(embeddings_dir, Path) else embeddings_dir
        embeddings_dir_path.mkdir(parents=True, exist_ok=True)

        safe_model_name = embedding.model_name.replace("/", "_")
        vector_file = (
            embeddings_dir_path
            / safe_model_name
            / f"image_{embedding.image_id}.npy"
        )
        vector_file.parent.mkdir(parents=True, exist_ok=True)
        vector = np.asarray(embedding.embedding_vector, dtype=np.float32)
        if vector.ndim != 1 or vector.size == 0:
            raise ProviderError("Embedding provider returned an empty or non-vector result")
        if not np.isfinite(vector).all():
            raise ProviderError("Embedding provider returned non-finite vector values")

        temporary_file = vector_file.with_name(f"{vector_file.stem}.{uuid4().hex}.tmp.npy")
        try:
            np.save(temporary_file, vector, allow_pickle=False)
            temporary_file.replace(vector_file)
        finally:
            temporary_file.unlink(missing_ok=True)
        return vector_file

    def _emit(self, event: object) -> None:
        """Emit event to callback."""
        if self.callback is not None:
            self.callback(event)
