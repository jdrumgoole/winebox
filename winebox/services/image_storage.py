"""Image storage service for managing wine label images."""

import uuid
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from winebox.config import settings


class ImageStorageService:
    """Service for storing and managing wine label images."""

    def __init__(self, storage_path: Path | None = None) -> None:
        """Initialize the image storage service.

        Args:
            storage_path: Path to store images. Defaults to config setting.
        """
        self.storage_path = storage_path or settings.image_storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def save_image(self, upload_file: UploadFile) -> str:
        """Save an uploaded image file.

        Args:
            upload_file: The uploaded file from FastAPI.

        Returns:
            The filename of the saved image.
        """
        # Generate unique filename
        ext = Path(upload_file.filename or "image.jpg").suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            ext = ".jpg"

        filename = f"{uuid.uuid4()}{ext}"
        file_path = self.storage_path / filename

        # Save file
        content = await upload_file.read()
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
