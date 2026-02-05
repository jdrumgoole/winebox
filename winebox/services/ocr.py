"""OCR service for extracting text from wine label images."""

import io
import logging
from pathlib import Path

from PIL import Image

from winebox.config import settings

logger = logging.getLogger(__name__)


class OCRService:
    """Service for extracting text from images using Tesseract OCR."""

    def __init__(self) -> None:
        """Initialize the OCR service."""
        # Configure Tesseract command if specified
        if settings.tesseract_cmd:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    async def extract_text(self, image_path: str | Path) -> str:
        """Extract text from an image file.

        Args:
            image_path: Path to the image file (relative to image storage).

        Returns:
            Extracted text from the image.
        """
        try:
            import pytesseract

            # Build full path if relative
            if isinstance(image_path, str) and not Path(image_path).is_absolute():
                full_path = settings.image_storage_path / image_path
            else:
                full_path = Path(image_path)

            if not full_path.exists():
                logger.warning(f"Image file not found: {full_path}")
                return ""

            # Open image and extract text
            image = Image.open(full_path)

            # Preprocess image for better OCR results
            # Convert to grayscale
            if image.mode != "L":
                image = image.convert("L")

            # Extract text
            text = pytesseract.image_to_string(
                image,
                lang="eng",
                config="--psm 6",  # Assume uniform block of text
            )

            return text.strip()

        except ImportError:
            logger.error("pytesseract is not installed")
            return ""
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return ""

    async def extract_text_from_bytes(self, image_data: bytes) -> str:
        """Extract text from image bytes without saving to disk.

        Args:
            image_data: Raw image data as bytes.

        Returns:
            Extracted text from the image.
        """
        try:
            import pytesseract

            # Open image from bytes
            image = Image.open(io.BytesIO(image_data))

            # Preprocess image for better OCR results
            # Convert to grayscale
            if image.mode != "L":
                image = image.convert("L")

            # Extract text
            text = pytesseract.image_to_string(
                image,
                lang="eng",
                config="--psm 6",  # Assume uniform block of text
            )

            return text.strip()

        except ImportError:
            logger.error("pytesseract is not installed")
            return ""
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return ""

    async def extract_text_with_confidence(
        self, image_path: str | Path
    ) -> tuple[str, float]:
        """Extract text from an image with confidence score.

        Args:
            image_path: Path to the image file.

        Returns:
            Tuple of (extracted_text, average_confidence).
        """
        try:
            import pytesseract

            # Build full path if relative
            if isinstance(image_path, str) and not Path(image_path).is_absolute():
                full_path = settings.image_storage_path / image_path
            else:
                full_path = Path(image_path)

            if not full_path.exists():
                logger.warning(f"Image file not found: {full_path}")
                return "", 0.0

            image = Image.open(full_path)

            if image.mode != "L":
                image = image.convert("L")

            # Get detailed data with confidence
            data = pytesseract.image_to_data(
                image,
                lang="eng",
                config="--psm 6",
                output_type=pytesseract.Output.DICT,
            )

            # Calculate average confidence for words
            confidences = [
                conf
                for conf, text in zip(data["conf"], data["text"])
                if conf > 0 and text.strip()
            ]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            # Get full text
            text = pytesseract.image_to_string(
                image,
                lang="eng",
                config="--psm 6",
            )

            return text.strip(), avg_confidence

        except ImportError:
            logger.error("pytesseract is not installed")
            return "", 0.0
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return "", 0.0
