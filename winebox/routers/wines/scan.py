"""Wine label scanning endpoint."""

import asyncio
import logging
from typing import Annotated

from fastapi import File, UploadFile

from winebox.services.auth import RequireAuth
from winebox.services.xwines_enrichment import enrich_parsed_with_xwines

from ._common import (
    get_media_type,
    ocr_service,
    validate_upload_size,
    vision_service,
    wine_parser,
)

logger = logging.getLogger(__name__)


async def scan_label(
    current_user: RequireAuth,
    front_label: Annotated[UploadFile, File(description="Front label image")],
    back_label: Annotated[UploadFile | None, File(description="Back label image")] = None,
) -> dict:
    """Scan wine label images and extract text without creating a wine record.

    Uses Claude Vision for intelligent label analysis when available,
    falls back to Tesseract OCR otherwise.
    """
    # Validate and read image data with size limits concurrently
    async def validate_front() -> bytes:
        return await validate_upload_size(front_label, "Front label")

    async def validate_back() -> bytes | None:
        if back_label and back_label.filename:
            return await validate_upload_size(back_label, "Back label")
        return None

    front_data, back_data = await asyncio.gather(validate_front(), validate_back())

    # Try Claude Vision first
    if vision_service.is_available():
        logger.info("Using Claude Vision for label analysis")
        try:
            front_media_type = get_media_type(front_label.filename)
            back_media_type = get_media_type(back_label.filename if back_label else None)

            result = await vision_service.analyze_labels(
                front_image_data=front_data,
                back_image_data=back_data,
                front_media_type=front_media_type,
                back_media_type=back_media_type,
            )

            # Build parsed dict and enrich with X-Wines data
            parsed = {
                "name": result.get("name"),
                "winery": result.get("winery"),
                "vintage": result.get("vintage"),
                "grape_variety": result.get("grape_variety"),
                "region": result.get("region"),
                "sub_region": result.get("sub_region"),
                "appellation": result.get("appellation"),
                "country": result.get("country"),
                "classification": result.get("classification"),
                "alcohol_percentage": result.get("alcohol_percentage"),
            }
            parsed = await enrich_parsed_with_xwines(parsed)

            return {
                "parsed": {
                    "name": parsed.get("name"),
                    "winery": parsed.get("winery"),
                    "vintage": parsed.get("vintage"),
                    "grape_variety": parsed.get("grape_variety"),
                    "region": parsed.get("region"),
                    "sub_region": parsed.get("sub_region"),
                    "appellation": parsed.get("appellation"),
                    "country": parsed.get("country"),
                    "classification": parsed.get("classification"),
                    "alcohol_percentage": parsed.get("alcohol_percentage"),
                    "wine_type": parsed.get("wine_type"),
                    "xwines_id": parsed.get("xwines_id"),
                },
                "ocr": {
                    "front_label_text": result.get("raw_text", ""),
                    "back_label_text": result.get("back_label_text"),
                },
                "method": "claude_vision",
            }
        except Exception as e:
            logger.warning(f"Claude Vision failed, falling back to Tesseract: {e}")

    # Fall back to Tesseract OCR
    logger.info("Using Tesseract OCR for label analysis")
    front_text = await ocr_service.extract_text_from_bytes(front_data)

    back_text = None
    if back_data:
        back_text = await ocr_service.extract_text_from_bytes(back_data)

    # Parse wine details from OCR text
    combined_text = front_text
    if back_text:
        combined_text = f"{front_text}\n{back_text}"
    parsed_data = wine_parser.parse(combined_text)
    parsed_data = await enrich_parsed_with_xwines(parsed_data)

    return {
        "parsed": {
            "name": parsed_data.get("name"),
            "winery": parsed_data.get("winery"),
            "vintage": parsed_data.get("vintage"),
            "grape_variety": parsed_data.get("grape_variety"),
            "region": parsed_data.get("region"),
            "sub_region": parsed_data.get("sub_region"),
            "appellation": parsed_data.get("appellation"),
            "country": parsed_data.get("country"),
            "classification": parsed_data.get("classification"),
            "alcohol_percentage": parsed_data.get("alcohol_percentage"),
            "wine_type": parsed_data.get("wine_type"),
            "xwines_id": parsed_data.get("xwines_id"),
        },
        "ocr": {
            "front_label_text": front_text,
            "back_label_text": back_text,
        },
        "method": "tesseract",
    }
