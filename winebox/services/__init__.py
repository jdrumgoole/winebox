"""Services for WineBox application."""

from winebox.services.image_storage import ImageStorageService
from winebox.services.ocr import OCRService
from winebox.services.wine_parser import WineParserService

__all__ = ["ImageStorageService", "OCRService", "WineParserService"]
