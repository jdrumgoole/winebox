"""Wine label scanning endpoint."""

import asyncio
import logging
from typing import Annotated

from fastapi import File, Request, UploadFile

from winebox.services.auth import RequireAuth
from winebox.services.rate_limit import make_limiter
from winebox.services.scan_service import scan_wine_labels
from winebox.services.xwines_enrichment import enrich_parsed_with_xwines

from ._common import (
    ocr_service,
    validate_upload_size,
    vision_service,
    wine_parser,
)

logger = logging.getLogger(__name__)

# Vision-bound and cost-bound — every scan can hit Claude.
limiter = make_limiter()


# Parsed fields that the /scan response exposes. Centralised so any
# future additions land in the response dict without code duplication.
_PARSED_KEYS = (
    "name",
    "winery",
    "vintage",
    "grape_variety",
    "region",
    "sub_region",
    "appellation",
    "country",
    "classification",
    "alcohol_percentage",
    "wine_type",
    "xwines_id",
)


@limiter.limit("20/minute;200/hour")
async def scan_label(
    request: Request,
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

    scanned = await scan_wine_labels(
        front_data=front_data,
        back_data=back_data,
        front_filename=front_label.filename,
        back_filename=back_label.filename if back_label else None,
        vision_service=vision_service,
        ocr_service=ocr_service,
        wine_parser=wine_parser,
    )

    # Enrich with X-Wines reference data (fills missing fields only).
    parsed = {k: scanned.parsed_data.get(k) for k in _PARSED_KEYS}
    parsed = await enrich_parsed_with_xwines(parsed)

    return {
        "parsed": {k: parsed.get(k) for k in _PARSED_KEYS},
        "ocr": {
            "front_label_text": scanned.front_text,
            "back_label_text": scanned.back_text,
        },
        "method": scanned.method,
    }
