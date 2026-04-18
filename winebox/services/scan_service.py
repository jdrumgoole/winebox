"""Wine label scanning: dispatches between Claude Vision and Tesseract.

Previously inlined in ``routers/wines/checkin.py`` as ~60 lines of
branching logic. Centralising it here keeps the scan strategy in one
place (so e.g. a future "always use Vision" or "prefer local OCR for
offline deployments" change lands once) and makes the router a thin
HTTP-plus-persistence layer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import UploadFile

from winebox.routers.wines._common import get_media_type
from winebox.services.ocr import OCRService
from winebox.services.vision import ClaudeVisionService
from winebox.services.wine_parser import WineParserService

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
    front_text: str = ""
    back_text: str | None = None
    method: str = "none"  # "claude_vision" | "tesseract" | "none"
    parsed_data: dict[str, Any] = field(default_factory=dict)


async def scan_wine_labels(
    front_label: UploadFile,
    back_label: UploadFile | None,
    front_image_path: str,
    back_image_path: str | None,
    vision_service: ClaudeVisionService,
    ocr_service: OCRService,
    wine_parser: WineParserService,
) -> ScannedLabels:
    """Extract wine metadata from label images.

    Prefers Claude Vision when available. On failure (or if Vision
    returned no usable name) falls back to Tesseract OCR + the
    heuristic wine parser. Reads the uploaded file payloads
    concurrently so the Vision call doesn't block on I/O.
    """
    async def read_front() -> bytes:
        await front_label.seek(0)
        return await front_label.read()

    async def read_back() -> bytes | None:
        if back_label and back_label.filename:
            await back_label.seek(0)
            return await back_label.read()
        return None

    front_data, back_data = await asyncio.gather(read_front(), read_back())

    parsed_data: dict[str, Any] = {}
    front_text = ""
    back_text: str | None = None
    method = "none"

    if vision_service.is_available():
        logger.info("Using Claude Vision for checkin analysis")
        try:
            front_media_type = get_media_type(front_label.filename)
            back_media_type = get_media_type(
                back_label.filename if back_label else None
            )
            result = await vision_service.analyze_labels(
                front_image_data=front_data,
                back_image_data=back_data,
                front_media_type=front_media_type,
                back_media_type=back_media_type,
            )
            parsed_data = result
            front_text = result.get("raw_text", "")
            back_text = result.get("back_label_text")
            method = "claude_vision"
        except Exception as exc:
            logger.warning(
                "Claude Vision failed, falling back to Tesseract: %s", exc
            )

    # Fall back to Tesseract when Vision unavailable or yielded no name.
    if not parsed_data.get("name"):
        logger.info("Using Tesseract OCR for checkin analysis")
        front_text = await ocr_service.extract_text(front_image_path)
        if back_image_path:
            back_text = await ocr_service.extract_text(back_image_path)

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
        front_text=front_text,
        back_text=back_text,
        method=method,
        parsed_data=parsed_data,
    )
