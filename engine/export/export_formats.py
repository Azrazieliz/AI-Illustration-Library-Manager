from __future__ import annotations

from abc import ABC, abstractmethod

from engine.export.export_models import ExportFormatType


class ExportFormat(ABC):
    """Extensible dataset export format contract."""

    format_type: ExportFormatType

    @abstractmethod
    def build_payload(self, base_payload: dict) -> dict:
        """Return export-format-specific payload from canonical base payload."""


class GenericDatasetFormat(ExportFormat):
    format_type = ExportFormatType.GENERIC

    def build_payload(self, base_payload: dict) -> dict:
        return {
            **base_payload,
            "dataset_type": "generic",
        }


class FluxDatasetFormat(ExportFormat):
    format_type = ExportFormatType.FLUX

    def build_payload(self, base_payload: dict) -> dict:
        return {
            **base_payload,
            "dataset_type": "flux",
            "flux": {
                "prompt": base_payload.get("caption", ""),
                "tags": base_payload.get("tags", []),
            },
        }


class SDXLDatasetFormat(ExportFormat):
    format_type = ExportFormatType.SDXL

    def build_payload(self, base_payload: dict) -> dict:
        image = base_payload.get("image", {})
        return {
            **base_payload,
            "dataset_type": "sdxl",
            "sdxl": {
                "caption": base_payload.get("caption", ""),
                "width": image.get("width"),
                "height": image.get("height"),
            },
        }


class StableDiffusionDatasetFormat(ExportFormat):
    format_type = ExportFormatType.STABLE_DIFFUSION

    def build_payload(self, base_payload: dict) -> dict:
        return {
            **base_payload,
            "dataset_type": "stable_diffusion",
            "stable_diffusion": {
                "prompt": base_payload.get("caption", ""),
                "negative_prompt": "",
                "tags": base_payload.get("tags", []),
            },
        }


class ComfyUIDatasetFormat(ExportFormat):
    format_type = ExportFormatType.COMFYUI

    def build_payload(self, base_payload: dict) -> dict:
        return {
            **base_payload,
            "dataset_type": "comfyui",
            "comfyui": {
                "workflow": "training_dataset_v1",
                "inputs": {
                    "image": base_payload.get("image", {}).get("path"),
                    "caption": base_payload.get("caption", ""),
                },
            },
        }


def build_default_formats() -> dict[ExportFormatType, ExportFormat]:
    formats: list[ExportFormat] = [
        GenericDatasetFormat(),
        FluxDatasetFormat(),
        SDXLDatasetFormat(),
        StableDiffusionDatasetFormat(),
        ComfyUIDatasetFormat(),
    ]
    return {handler.format_type: handler for handler in formats}
