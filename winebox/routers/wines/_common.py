"""Common utilities and service instances for wine endpoints."""

import logging

from fastapi import HTTPException, UploadFile, status

from winebox.config import settings
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
