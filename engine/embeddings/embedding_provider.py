from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from engine.embeddings.embedding_exceptions import (
    ProviderError,
    UnsupportedProviderError,
)
from engine.embeddings.embedding_models import ExtractedEmbedding
from engine.logging import get_logger


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    def __init__(
        self,
        model_name: str,
        model_version: str = "1.0.0",
        device: str = "cpu",
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self.device = device
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the provider and load the model."""
        pass

    @abstractmethod
    def extract(self, image_path: Path | str) -> list[float]:
        """Extract embedding vector from image.

        Returns:
            List of floats representing the embedding vector.
        """
        pass

    @abstractmethod
    def get_dimensions(self) -> int:
        """Get the embedding vector dimensions."""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the provider name (e.g., 'clip', 'openclip', 'siglip')."""
        pass

    def extract_embedding(self, image_id: int, path: Path | str) -> ExtractedEmbedding:
        """Extract embedding for an image and wrap in ExtractedEmbedding."""
        vector = self.extract(path)
        return ExtractedEmbedding(
            image_id=image_id,
            embedding_vector=vector,
            model_name=self.model_name,
            model_version=self.model_version,
            dimensions=len(vector),
            provider_name=self.get_provider_name(),
        )


class CLIPProvider(EmbeddingProvider):
    """CLIP-based embedding provider using OpenAI's CLIP.

    Supports:
    - openai/clip-vit-base-patch32
    - openai/clip-vit-large-patch14
    - And other OpenAI CLIP models
    """

    def __init__(
        self,
        model_name: str = "openai/clip-vit-base-patch32",
        model_version: str = "1.0.0",
        device: str = "cpu",
    ) -> None:
        super().__init__(model_name, model_version, device)
        self.model = None
        self.processor = None

    def initialize(self) -> None:
        """Initialize CLIP model and processor."""
        try:
            from transformers import CLIPModel, CLIPProcessor

            self.logger.info(f"Loading CLIP model: {self.model_name}")
            self.model = CLIPModel.from_pretrained(self.model_name)
            self.processor = CLIPProcessor.from_pretrained(self.model_name)
            self.model = self.model.to(self.device)
            self.logger.info("CLIP model loaded successfully")
        except ImportError as e:
            raise ProviderError(
                "transformers library required for CLIP provider"
            ) from e
        except Exception as e:
            raise ProviderError(f"Failed to initialize CLIP provider: {e}") from e

    def extract(self, image_path: Path | str) -> list[float]:
        """Extract embedding from image using CLIP."""
        if self.model is None or self.processor is None:
            raise ProviderError("Provider not initialized. Call initialize() first.")

        try:
            from PIL import Image

            image = Image.open(image_path).convert("RGB")
            inputs = self.processor(
                images=image, return_tensors="pt", padding=True
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with __import__("torch").no_grad():
                image_features = self.model.get_image_features(**inputs)
                image_features = image_features / image_features.norm(
                    dim=-1, keepdim=True
                )

            return image_features[0].cpu().tolist()
        except Exception as e:
            raise ProviderError(f"Failed to extract embedding: {e}") from e

    def get_dimensions(self) -> int:
        """Get CLIP embedding dimensions."""
        if self.model is None:
            raise ProviderError("Provider not initialized. Call initialize() first.")
        return self.model.config.projection_dim

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "clip"


class MockProvider(EmbeddingProvider):
    """Mock provider for testing without GPU dependencies."""

    def __init__(
        self,
        model_name: str = "mock",
        model_version: str = "1.0.0",
        device: str = "cpu",
        dimensions: int = 512,
    ) -> None:
        super().__init__(model_name, model_version, device)
        self._dimensions = dimensions

    def initialize(self) -> None:
        """Initialize mock provider (no-op)."""
        self.logger.info("Mock provider initialized")

    def extract(self, image_path: Path | str) -> list[float]:
        """Generate mock embedding vector."""
        import hashlib

        path_str = str(image_path)
        hash_digest = hashlib.md5(path_str.encode()).digest()
        vector = [
            float(b) / 256.0 for b in hash_digest for _ in range(self._dimensions // 16)
        ]
        return vector[: self._dimensions]

    def get_dimensions(self) -> int:
        """Get mock embedding dimensions."""
        return self._dimensions

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "mock"


def get_provider(
    provider_type: str = "clip",
    model_name: str | None = None,
    device: str = "cpu",
    **kwargs: Any,
) -> EmbeddingProvider:
    """Factory function to create embedding providers.

    Args:
        provider_type: Type of provider ('clip', 'mock')
        model_name: Model name/identifier
        device: Device to use ('cpu', 'cuda', 'mps')
        **kwargs: Additional arguments for provider

    Returns:
        EmbeddingProvider instance

    Raises:
        UnsupportedProviderError: If provider type is not supported
    """
    if provider_type == "clip":
        model = model_name or "openai/clip-vit-base-patch32"
        return CLIPProvider(model_name=model, device=device)
    elif provider_type == "mock":
        dimensions = kwargs.get("dimensions", 512)
        return MockProvider(dimensions=dimensions, device=device)
    else:
        raise UnsupportedProviderError(f"Unknown provider: {provider_type}")
