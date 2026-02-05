"""Image storage service for managing wine label images."""

import uuid
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile, status

from winebox.config import settings

# Allowed MIME types for image uploads
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

# File extension to MIME type mapping
EXTENSION_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Magic byte signatures for image formats
# Each entry is (magic_bytes, offset, detected_extension)
IMAGE_MAGIC_SIGNATURES = [
    # JPEG: starts with FF D8 FF
    (b"\xff\xd8\xff", 0, ".jpg"),
    # PNG: starts with 89 50 4E 47 0D 0A 1A 0A
    (b"\x89PNG\r\n\x1a\n", 0, ".png"),
    # GIF87a and GIF89a
    (b"GIF87a", 0, ".gif"),
    (b"GIF89a", 0, ".gif"),
    # WebP: starts with RIFF....WEBP
    (b"RIFF", 0, ".webp"),  # Additional check for WEBP at offset 8
]


def detect_image_type(content: bytes) -> str | None:
    """Detect image type from file content using magic bytes.

    Args:
        content: The file content bytes.

    Returns:
        The detected extension (e.g., ".jpg") or None if not a valid image.
    """
    if len(content) < 12:
        return None

    for magic, offset, ext in IMAGE_MAGIC_SIGNATURES:
        if content[offset:offset + len(magic)] == magic:
            # Special case for WebP: verify WEBP signature at offset 8
            if ext == ".webp":
                if content[8:12] != b"WEBP":
                    continue
            return ext

    return None


class FileSizeExceededError(Exception):
    """Raised when uploaded file exceeds size limit."""

    pass


class InvalidFileTypeError(Exception):
    """Raised when uploaded file has invalid type."""

    pass


class InvalidMagicBytesError(Exception):
    """Raised when file content doesn't match a valid image format."""

    pass


class ImageStorageService:
    """Service for storing and managing wine label images."""

    def __init__(
        self,
        storage_path: Path | None = None,
        max_size_bytes: int | None = None,
    ) -> None:
        """Initialize the image storage service.

        Args:
            storage_path: Path to store images. Defaults to config setting.
            max_size_bytes: Maximum file size in bytes. Defaults to config setting.
        """
        self.storage_path = storage_path or settings.image_storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.max_size_bytes = max_size_bytes or settings.max_upload_size_bytes

    def _validate_extension(self, filename: str | None) -> str:
        """Validate and return the file extension.

        Args:
            filename: The original filename.

        Returns:
            Valid extension (e.g., ".jpg").

        Raises:
            InvalidFileTypeError: If extension is not allowed.
        """
        if not filename:
            return ".jpg"

        ext = Path(filename).suffix.lower()
        if ext not in EXTENSION_MIME_MAP:
            raise InvalidFileTypeError(
                f"Invalid file type. Allowed types: {', '.join(EXTENSION_MIME_MAP.keys())}"
            )
        return ext

    async def save_image(self, upload_file: UploadFile) -> str:
        """Save an uploaded image file with size, type, and content validation.

        Args:
            upload_file: The uploaded file from FastAPI.

        Returns:
            The filename of the saved image.

        Raises:
            HTTPException: If file exceeds size limit, has invalid type, or
                          content doesn't match a valid image format.
        """
        # Validate extension first
        try:
            declared_ext = self._validate_extension(upload_file.filename)
        except InvalidFileTypeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        # Read content with size limit check
        content = await upload_file.read()
        if len(content) > self.max_size_bytes:
            max_mb = self.max_size_bytes / (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File size exceeds maximum allowed size of {max_mb:.1f} MB",
            )

        # Validate magic bytes - ensure file content matches a valid image format
        detected_ext = detect_image_type(content)
        if detected_ext is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file content. File does not appear to be a valid image.",
            )

        # Use the detected extension (more reliable than declared extension)
        # This prevents attacks where malicious files are renamed to .jpg/.png
        ext = detected_ext

        # Generate unique filename with detected extension
        filename = f"{uuid.uuid4()}{ext}"
        file_path = self.storage_path / filename

        # Save file
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)

        return filename

    async def delete_image(self, filename: str) -> bool:
        """Delete an image file.

        Args:
            filename: The filename to delete.

        Returns:
            True if deleted, False if not found.
        """
        file_path = self.storage_path / filename

        if file_path.exists():
            file_path.unlink()
            return True

        return False

    def get_image_path(self, filename: str) -> Path | None:
        """Get the full path to an image file.

        Args:
            filename: The filename to look up.

        Returns:
            The full path if file exists, None otherwise.
        """
        file_path = self.storage_path / filename

        if file_path.exists():
            return file_path

        return None

    def get_image_url(self, filename: str) -> str:
        """Get the URL path for an image.

        Args:
            filename: The image filename.

        Returns:
            The URL path to access the image.
        """
        return f"/api/images/{filename}"
