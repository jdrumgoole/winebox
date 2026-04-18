"""Wine label scanning: dispatches between Claude Vision and Tesseract.

Centralises the "try Vision first, fall back to Tesseract if it's off
or returned no usable name" strategy that both the /wines/scan endpoint
(scan-only, no persistence) and the /wines/record endpoint
(scan + persist) need.

Inputs are raw bytes + a filename (for media-type inference) so the
service is agnostic to whether the caller already saved the image to
disk or kept it in memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from winebox.services.ocr import OCRService
from winebox.services.vision import ClaudeVisionService
from winebox.services.wine_parser import WineParserService


# Inlined (rather than imported from routers.wines._common) to avoid a
# circular import — scan_service is a dependency of the routers, not the
# other way round.
_MEDIA_TYPE_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _media_type_for(filename: str | None) -> str:
    if not filename:
        return "image/jpeg"
    ext = filename.lower().rsplit(".", 1)[-1]
    return _MEDIA_TYPE_BY_EXT.get(ext, "image/jpeg")

logger = logging.getLogger(__name__)


@dataclass
class ScannedLabels:
    """Result of a label scan. Fields default to None when unknown."""

    name: str | None = None
    winery: str | None = None
    vintage: int | None = None
    grape_variety: str | None = None
    region: str | None = None
    sub_region: str | None = None
    appellation: str | None = None
    country: str | None = None
    classification: str | None = None
    alcohol_percentage: float | None = None
    wine_type: str | None = None
    xwines_id: int | None = None
    front_text: str = ""
    back_text: str | None = None
    method: str = "none"  # "claude_vision" | "tesseract" | "none"
    parsed_data: dict[str, Any] = field(default_factory=dict)


async def scan_wine_labels(
    front_data: bytes,
    back_data: bytes | None,
    front_filename: str | None,
    back_filename: str | None,
    vision_service: ClaudeVisionService,
    ocr_service: OCRService,
    wine_parser: WineParserService,
) -> ScannedLabels:
    """Extract wine metadata from label image bytes.

    Prefers Claude Vision when available. On failure (or if Vision
    returned no usable name) falls back to Tesseract OCR on the same
    bytes plus the heuristic wine parser.
    """
    parsed_data: dict[str, Any] = {}
    front_text = ""
    back_text: str | None = None
    method = "none"

    if vision_service.is_available():
        logger.info("Using Claude Vision for label analysis")
        try:
            result = await vision_service.analyze_labels(
                front_image_data=front_data,
                back_image_data=back_data,
                front_media_type=_media_type_for(front_filename),
                back_media_type=_media_type_for(back_filename),
            )
            parsed_data = result
            front_text = result.get("raw_text", "")
            back_text = result.get("back_label_text")
            method = "claude_vision"
        except Exception as exc:
            logger.warning(
                "Claude Vision failed, falling back to Tesseract: %s", exc
            )

    # Fall back to Tesseract when Vision is disabled or yielded no name.
    if not parsed_data.get("name"):
        logger.info("Using Tesseract OCR for label analysis")
        front_text = await ocr_service.extract_text_from_bytes(front_data)
        if back_data is not None:
            back_text = await ocr_service.extract_text_from_bytes(back_data)

        combined_text = front_text
        if back_text:
            combined_text = f"{front_text}\n{back_text}"
        parsed_data = wine_parser.parse(combined_text)
        method = "tesseract"

    return ScannedLabels(
        name=parsed_data.get("name"),
        winery=parsed_data.get("winery"),
        vintage=parsed_data.get("vintage"),
        grape_variety=parsed_data.get("grape_variety"),
        region=parsed_data.get("region"),
        sub_region=parsed_data.get("sub_region"),
        appellation=parsed_data.get("appellation"),
        country=parsed_data.get("country"),
        classification=parsed_data.get("classification"),
        alcohol_percentage=parsed_data.get("alcohol_percentage"),
        wine_type=parsed_data.get("wine_type"),
        xwines_id=parsed_data.get("xwines_id"),
        front_text=front_text,
        back_text=back_text,
        method=method,
        parsed_data=parsed_data,
    )
