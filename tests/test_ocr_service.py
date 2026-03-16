"""Tests for the OCR service (extract_text, extract_text_from_bytes, extract_text_with_confidence)."""

import io
import pytest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from winebox.services.ocr import OCRService


@pytest.fixture
def ocr_service():
    """Create an OCR service instance."""
    with patch("winebox.config.settings") as mock_settings:
        mock_settings.tesseract_cmd = ""
        mock_settings.image_storage_path = Path("/tmp/test-images")
        return OCRService()


@pytest.fixture
def sample_image(tmp_path) -> Path:
    """Create a sample image for OCR testing."""
    img = Image.new("RGB", (100, 30), color="white")
    path = tmp_path / "test_label.png"
    img.save(path)
    return path


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Create sample image bytes."""
    img = Image.new("RGB", (100, 30), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestExtractText:
    """Tests for OCRService.extract_text."""

    @pytest.mark.asyncio
    async def test_extract_text_success(self, ocr_service, sample_image):
        with patch("pytesseract.image_to_string", return_value="Château Margaux 2015"):
            result = await ocr_service.extract_text(sample_image)
            assert result == "Château Margaux 2015"

    @pytest.mark.asyncio
    async def test_extract_text_relative_path(self, ocr_service, tmp_path):
        img = Image.new("L", (100, 30), color="white")
        (tmp_path / "labels").mkdir()
        img.save(tmp_path / "labels" / "test.png")

        with patch("winebox.services.ocr.settings") as mock_settings:
            mock_settings.image_storage_path = tmp_path
            with patch("pytesseract.image_to_string", return_value="test"):
                result = await ocr_service.extract_text("labels/test.png")
                assert result == "test"

    @pytest.mark.asyncio
    async def test_extract_text_file_not_found(self, ocr_service):
        result = await ocr_service.extract_text("/nonexistent/path.png")
        assert result == ""

    @pytest.mark.asyncio
    async def test_extract_text_converts_to_grayscale(self, ocr_service, sample_image):
        with patch("pytesseract.image_to_string", return_value="text") as mock_ocr:
            await ocr_service.extract_text(sample_image)
            img_arg = mock_ocr.call_args[0][0]
            assert img_arg.mode == "L"

    @pytest.mark.asyncio
    async def test_extract_text_already_grayscale(self, ocr_service, tmp_path):
        img = Image.new("L", (100, 30), color=128)
        path = tmp_path / "gray.png"
        img.save(path)
        with patch("pytesseract.image_to_string", return_value="text") as mock_ocr:
            await ocr_service.extract_text(path)
            img_arg = mock_ocr.call_args[0][0]
            assert img_arg.mode == "L"

    @pytest.mark.asyncio
    async def test_extract_text_strips_whitespace(self, ocr_service, sample_image):
        with patch("pytesseract.image_to_string", return_value="  text with spaces  \n"):
            result = await ocr_service.extract_text(sample_image)
            assert result == "text with spaces"

    @pytest.mark.asyncio
    async def test_extract_text_general_exception(self, ocr_service, sample_image):
        with patch("pytesseract.image_to_string", side_effect=RuntimeError("OCR crash")):
            result = await ocr_service.extract_text(sample_image)
            assert result == ""


class TestExtractTextFromBytes:
    """Tests for OCRService.extract_text_from_bytes."""

    @pytest.mark.asyncio
    async def test_extract_from_bytes_success(self, ocr_service, sample_image_bytes):
        with patch("pytesseract.image_to_string", return_value="Label Text"):
            result = await ocr_service.extract_text_from_bytes(sample_image_bytes)
            assert result == "Label Text"

    @pytest.mark.asyncio
    async def test_extract_from_bytes_grayscale(self, ocr_service, sample_image_bytes):
        with patch("pytesseract.image_to_string", return_value="text") as mock_ocr:
            await ocr_service.extract_text_from_bytes(sample_image_bytes)
            img_arg = mock_ocr.call_args[0][0]
            assert img_arg.mode == "L"

    @pytest.mark.asyncio
    async def test_extract_from_bytes_error(self, ocr_service):
        img = Image.new("RGB", (10, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        with patch("pytesseract.image_to_string", side_effect=Exception("OCR failed")):
            result = await ocr_service.extract_text_from_bytes(buf.getvalue())
            assert result == ""


class TestExtractTextWithConfidence:
    """Tests for OCRService.extract_text_with_confidence."""

    @pytest.mark.asyncio
    async def test_with_confidence_success(self, ocr_service, sample_image):
        mock_data = {
            "conf": [95, 88, -1, 92],
            "text": ["Château", "Margaux", "", "2015"],
        }
        with patch("pytesseract.image_to_data", return_value=mock_data), \
             patch("pytesseract.image_to_string", return_value="Château Margaux 2015"), \
             patch("pytesseract.Output") as mock_output:
            mock_output.DICT = "dict"
            text, confidence = await ocr_service.extract_text_with_confidence(sample_image)
            assert text == "Château Margaux 2015"
            assert confidence == pytest.approx((95 + 88 + 92) / 3)

    @pytest.mark.asyncio
    async def test_with_confidence_file_not_found(self, ocr_service):
        text, confidence = await ocr_service.extract_text_with_confidence("/nonexistent.png")
        assert text == ""
        assert confidence == 0.0

    @pytest.mark.asyncio
    async def test_with_confidence_no_words(self, ocr_service, sample_image):
        mock_data = {
            "conf": [-1, -1],
            "text": ["", ""],
        }
        with patch("pytesseract.image_to_data", return_value=mock_data), \
             patch("pytesseract.image_to_string", return_value=""), \
             patch("pytesseract.Output") as mock_output:
            mock_output.DICT = "dict"
            text, confidence = await ocr_service.extract_text_with_confidence(sample_image)
            assert confidence == 0.0

    @pytest.mark.asyncio
    async def test_with_confidence_error(self, ocr_service, sample_image):
        with patch("pytesseract.image_to_data", side_effect=RuntimeError("crash")):
            text, confidence = await ocr_service.extract_text_with_confidence(sample_image)
            assert text == ""
            assert confidence == 0.0
