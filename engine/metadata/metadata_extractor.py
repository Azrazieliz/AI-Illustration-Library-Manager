from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image as PillowImage
from PIL import UnidentifiedImageError

from engine.metadata.metadata_exceptions import (
    CorruptedImageError,
    MetadataExtractionError,
    UnsupportedImageFormatError,
)
from engine.metadata.metadata_models import ExtractedMetadata


class MetadataExtractor:
    """Extracts image metadata using Pillow and EXIF inspection.

    Gracefully handles missing EXIF, corrupted metadata, unsupported
    formats, and partially readable images.
    """

    # MIME type mapping from Pillow format
    _FORMAT_TO_MIME: dict[str, str] = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "GIF": "image/gif",
        "WEBP": "image/webp",
        "BMP": "image/bmp",
        "TIFF": "image/tiff",
        "ICO": "image/x-icon",
        "PPM": "image/x-portable-pixmap",
        "PGM": "image/x-portable-graymap",
        "PBM": "image/x-portable-bitmap",
        "SGI": "image/sgi",
        "XBM": "image/x-xbitmap",
        "XPM": "image/x-xpixmap",
        "SUN_RASTER": "image/x-sun-raster",
    }

    @staticmethod
    def extract(path: Path | str) -> ExtractedMetadata:
        """Extract metadata from an image file.

        Raises
        ------
        UnsupportedImageFormatError
            If Pillow cannot identify the image format.
        CorruptedImageError
            If the image is corrupted or unreadable.
        MetadataExtractionError
            If extraction fails for other reasons.
        """
        resolved_path = Path(path).resolve()

        if not resolved_path.is_file():
            raise MetadataExtractionError(f"File not found: {resolved_path}")

        metadata = ExtractedMetadata(path=resolved_path)

        try:
            with PillowImage.open(resolved_path) as img:
                # Basic image properties
                metadata.width = img.width
                metadata.height = img.height

                if metadata.width and metadata.height:
                    metadata.aspect_ratio = metadata.width / metadata.height

                # Color mode and format
                metadata.color_mode = img.mode
                metadata.mime_type = MetadataExtractor._FORMAT_TO_MIME.get(
                    img.format, f"image/{img.format.lower() if img.format else 'unknown'}"
                )

                # Bit depth estimation
                metadata.bit_depth = MetadataExtractor._estimate_bit_depth(img)

                # DPI information
                metadata.dpi = MetadataExtractor._extract_dpi(img)

                # ICC profile
                metadata.has_icc_profile = img.info.get("icc_profile") is not None

                # Animation
                is_anim = hasattr(img, "is_animated") and img.is_animated
                metadata.is_animated = is_anim
                if is_anim:
                    metadata.frame_count = getattr(img, "n_frames", None)

                # EXIF metadata
                try:
                    metadata.exif_data = MetadataExtractor._extract_exif(img)
                    metadata.orientation = MetadataExtractor._extract_orientation_from_exif(
                        img
                    )
                except Exception:
                    # EXIF extraction is optional; don't fail the whole extraction
                    metadata.exif_data = None
                    metadata.orientation = None

        except UnidentifiedImageError as e:
            # Check if the error message suggests a corrupted/truncated file
            error_str = str(e).lower()
            if "truncated" in error_str or "eof" in error_str or "incomplete" in error_str:
                raise CorruptedImageError(
                    f"Image is corrupted or truncated: {resolved_path}"
                ) from e
            raise UnsupportedImageFormatError(
                f"Cannot identify image format: {resolved_path}"
            ) from e
        except Exception as e:
            # Check if it's a corrupted image issue
            if "truncated" in str(e).lower() or "eof" in str(e).lower():
                raise CorruptedImageError(
                    f"Image is corrupted or truncated: {resolved_path}"
                ) from e
            raise MetadataExtractionError(
                f"Metadata extraction failed: {resolved_path}: {e}"
            ) from e

        return metadata

    @staticmethod
    def _estimate_bit_depth(img: PillowImage.Image) -> int | None:
        """Estimate bit depth from color mode and image properties."""
        mode_to_depth: dict[str, int] = {
            "1": 1,  # 1-bit (black and white)
            "L": 8,  # 8-bit grayscale
            "P": 8,  # 8-bit palette
            "RGB": 24,  # 8 bits per channel
            "RGBA": 32,  # 8 bits per channel + alpha
            "CMYK": 32,  # 8 bits per channel
            "LAB": 24,  # 8 bits per channel
            "YCbCr": 24,  # 8 bits per channel
            "I": 32,  # 32-bit signed integer
            "F": 32,  # 32-bit floating point
            "LA": 16,  # 8 bits per channel + alpha
            "PA": 16,  # 8 bits per channel + alpha
            "RGBA": 32,
            "RGBa": 32,
        }
        return mode_to_depth.get(img.mode)

    @staticmethod
    def _extract_dpi(img: PillowImage.Image) -> str | None:
        """Extract DPI information from image info."""
        dpi_tuple = img.info.get("dpi")
        if dpi_tuple and isinstance(dpi_tuple, tuple) and len(dpi_tuple) == 2:
            return f"{dpi_tuple[0]},{dpi_tuple[1]}"
        return None

    @staticmethod
    def _extract_exif(img: PillowImage.Image) -> str | None:
        """Extract EXIF data as JSON string (subset of useful fields)."""
        try:
            from PIL import Image

            exif_data = img.getexif()
            if not exif_data:
                return None

            # Map of useful EXIF tags
            useful_tags: dict[int, str] = {
                0x0102: "bits_per_sample",
                0x0103: "compression",
                0x0106: "photometric_interpretation",
                0x0112: "orientation",
                0x011A: "xresolution",
                0x011B: "yresolution",
                0x011C: "resolution_unit",
                0x0131: "software",
                0x0132: "datetime",
                0x8827: "iso_speed",
                0x9000: "exif_version",
                0x9003: "datetime_original",
                0x9004: "datetime_digitized",
                0xA002: "pixel_x_dimension",
                0xA003: "pixel_y_dimension",
            }

            filtered_exif: dict[str, Any] = {}
            for tag_id, tag_name in useful_tags.items():
                if tag_id in exif_data:
                    try:
                        filtered_exif[tag_name] = str(exif_data[tag_id])
                    except Exception:
                        pass

            if filtered_exif:
                return json.dumps(filtered_exif)
            return None
        except Exception:
            return None

    @staticmethod
    def _extract_orientation_from_exif(img: PillowImage.Image) -> str | None:
        """Extract and normalize EXIF orientation tag."""
        try:
            exif_data = img.getexif()
            if not exif_data:
                return None

            # EXIF orientation tag ID
            orientation_tag = 0x0112
            if orientation_tag not in exif_data:
                return None

            orientation_value = exif_data[orientation_tag]
            orientation_map: dict[int, str] = {
                1: "normal",
                2: "flipped_horizontal",
                3: "rotated_180",
                4: "flipped_vertical",
                5: "rotated_270_flipped_horizontal",
                6: "rotated_90",
                7: "rotated_90_flipped_horizontal",
                8: "rotated_270",
            }

            return orientation_map.get(orientation_value, "unknown")
        except Exception:
            return None
