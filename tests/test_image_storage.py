"""Tests for image storage service - magic byte detection and file saving."""

import io
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile

from winebox.services.image_storage import ImageStorageService, detect_image_type


class TestDetectImageType:
    """Tests for detect_image_type function."""

    def test_detect_image_type_png(self, sample_image_bytes: bytes):
        """PNG magic bytes -> .png."""
        assert detect_image_type(sample_image_bytes) == ".png"

    def test_detect_image_type_jpeg(self):
        """JPEG magic bytes -> .jpg."""
        jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 20
        assert detect_image_type(jpeg_header) == ".jpg"

    def test_detect_image_type_gif87a(self):
        """GIF87a -> .gif."""
        gif_data = b"GIF87a" + b"\x00" * 20
        assert detect_image_type(gif_data) == ".gif"

    def test_detect_image_type_gif89a(self):
        """GIF89a -> .gif."""
        gif_data = b"GIF89a" + b"\x00" * 20
        assert detect_image_type(gif_data) == ".gif"

    def test_detect_image_type_webp(self):
        """RIFF+WEBP header -> .webp."""
        webp_data = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20
        assert detect_image_type(webp_data) == ".webp"

    def test_detect_image_type_invalid(self):
        """Random bytes -> None."""
        random_data = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d"
        assert detect_image_type(random_data) is None

    def test_detect_image_type_too_short(self):
        """<12 bytes -> None."""
        assert detect_image_type(b"\x89PNG") is None

    def test_detect_riff_without_webp(self):
        """RIFF header without WEBP signature -> None."""
        riff_data = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 20
        assert detect_image_type(riff_data) is None


@pytest.mark.asyncio
class TestImageStorageService:
    """Tests for ImageStorageService save/validate."""

    async def test_save_image_success(
        self, temp_image_dir: Path, sample_image_bytes: bytes
    ):
        """Valid PNG saved to disk."""
        service = ImageStorageService(
            storage_path=temp_image_dir, max_size_bytes=10 * 1024 * 1024
        )

        upload = UploadFile(
            filename="test.png",
            file=io.BytesIO(sample_image_bytes),
        )

        filename = await service.save_image(upload)
        assert filename.endswith(".png")
        assert (temp_image_dir / filename).exists()

    async def test_save_image_rejects_oversized(
        self, temp_image_dir: Path, sample_image_bytes: bytes
    ):
        """Large file -> HTTPException 413."""
        service = ImageStorageService(
            storage_path=temp_image_dir, max_size_bytes=10  # 10 bytes max
        )

        upload = UploadFile(
            filename="test.png",
            file=io.BytesIO(sample_image_bytes),
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.save_image(upload)
        assert exc_info.value.status_code == 413

    async def test_save_image_rejects_bad_magic(self, temp_image_dir: Path):
        """.png extension but text content -> 400."""
        service = ImageStorageService(
            storage_path=temp_image_dir, max_size_bytes=10 * 1024 * 1024
        )

        upload = UploadFile(
            filename="fake.png",
            file=io.BytesIO(b"This is not an image file at all, just text content"),
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.save_image(upload)
        assert exc_info.value.status_code == 400
