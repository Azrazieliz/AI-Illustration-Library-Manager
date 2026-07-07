from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from engine.logging import get_logger
from engine.recognition.recognition_exceptions import (
    RecognitionProviderError,
    UnsupportedRecognitionProviderError,
)
from engine.recognition.recognition_models import RecognitionLabel, RecognitionOutput


class RecognitionProvider(ABC):
    """Abstract base class for recognition providers."""

    def __init__(
        self,
        model_name: str,
        model_version: str = "1.0.0",
        device: str = "cpu",
        **_: Any,
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self.device = device
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def initialize(self) -> None:
        """Initialize provider resources."""

    @abstractmethod
    def recognize(self, image_path: Path | str) -> RecognitionOutput:
        """Recognize series/characters from an image path."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return provider short name."""


class MockRecognitionProvider(RecognitionProvider):
    """Deterministic mock provider based on the file name."""

    def __init__(
        self,
        model_name: str = "mock-recognition",
        model_version: str = "1.0.0",
        device: str = "cpu",
    ) -> None:
        super().__init__(model_name=model_name, model_version=model_version, device=device)

    def initialize(self) -> None:
        self.logger.info("Mock recognition provider initialized")

    def recognize(self, image_path: Path | str) -> RecognitionOutput:
        try:
            stem = Path(image_path).stem.strip()
            if not stem:
                return RecognitionOutput(
                    provider_name=self.get_provider_name(),
                    model_name=self.model_name,
                    model_version=self.model_version,
                )

            series_name, character_names = self._parse_stem(stem)
            series_label = (
                RecognitionLabel(name=series_name, confidence=self._confidence(stem, "series"))
                if series_name
                else None
            )
            character_labels = [
                RecognitionLabel(
                    name=name,
                    confidence=self._confidence(stem, f"character:{name}"),
                )
                for name in character_names
            ]

            return RecognitionOutput(
                series=series_label,
                characters=character_labels,
                provider_name=self.get_provider_name(),
                model_name=self.model_name,
                model_version=self.model_version,
            )
        except Exception as e:
            raise RecognitionProviderError(f"Failed to recognize image: {e}") from e

    def get_provider_name(self) -> str:
        return "mock"

    @staticmethod
    def _normalize_name(raw: str) -> str:
        text = raw.replace("_", " ").replace("-", " ").strip()
        if not text:
            return ""
        return " ".join(part.capitalize() for part in text.split())

    def _parse_stem(self, stem: str) -> tuple[str | None, list[str]]:
        parts = stem.split("__", maxsplit=1)
        series = self._normalize_name(parts[0]) if parts else ""
        if len(parts) == 1:
            return (series or None, [])

        chars_raw = parts[1].replace("|", "+")
        seen: set[str] = set()
        character_names: list[str] = []
        for item in chars_raw.split("+"):
            normalized = self._normalize_name(item)
            if normalized and normalized not in seen:
                seen.add(normalized)
                character_names.append(normalized)
        return (series or None, character_names)

    @staticmethod
    def _confidence(stem: str, salt: str) -> float:
        digest = hashlib.md5(f"{salt}:{stem}".encode("utf-8")).digest()
        # Keep confidence deterministic and in a realistic high-confidence range.
        return round(0.7 + (digest[0] / 255.0) * 0.29, 4)


def get_provider(
    provider_type: str = "mock",
    model_name: str | None = None,
    device: str = "cpu",
    **kwargs: Any,
) -> RecognitionProvider:
    """Factory for recognition providers."""
    if provider_type == "mock":
        return MockRecognitionProvider(
            model_name=model_name or "mock-recognition",
            device=device,
            model_version=kwargs.get("model_version", "1.0.0"),
        )

    raise UnsupportedRecognitionProviderError(f"Unknown recognition provider: {provider_type}")
