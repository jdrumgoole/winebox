"""Common utilities and service instances for wine endpoints."""

import logging
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile, status
from pydantic import ValidationError

from winebox.config import settings
from winebox.models import Wine
from winebox.services.image_storage import ImageStorageService
from winebox.services.ocr import OCRService
from winebox.services.vision import ClaudeVisionService
from winebox.services.wine_parser import WineParserService

logger = logging.getLogger(__name__)

# Maximum lengths for form fields (security limits)
MAX_NAME_LENGTH = 500
MAX_FIELD_LENGTH = 200
MAX_NOTES_LENGTH = 2000
MAX_OCR_TEXT_LENGTH = 10000

# Service dependencies
image_storage = ImageStorageService()
ocr_service = OCRService()
wine_parser = WineParserService()
vision_service = ClaudeVisionService()


async def validate_upload_size(upload_file: UploadFile, field_name: str) -> bytes:
    """Validate file size and return content.

    Args:
        upload_file: The uploaded file.
        field_name: Name of the field for error messages.

    Returns:
        The file content as bytes.

    Raises:
        HTTPException: If file exceeds size limit.
    """
    content = await upload_file.read()
    await upload_file.seek(0)

    if len(content) > settings.max_upload_size_bytes:
        max_mb = settings.max_upload_size_bytes / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"{field_name} exceeds maximum allowed size of {max_mb:.1f} MB",
        )
    return content


async def get_wine_or_404(wine_id: str, owner_id: Any) -> Wine:
    """Look up a wine by ID for the given owner, or raise 404.

    Centralises the InvalidId/ValidationError → 404 translation so every
    wine endpoint returns the same shape of error for a missing or
    malformed ID.
    """
    try:
        wine = await Wine.find_one({"_id": ObjectId(wine_id), "owner_id": owner_id})
    except (InvalidId, ValidationError) as e:
        logger.debug("Invalid wine ID format: %s - %s", wine_id, e)
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )
    return wine


def get_media_type(filename: str | None) -> str:
    """Get media type from filename."""
    if not filename:
        return "image/jpeg"
    ext = filename.lower().split(".")[-1]
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")
