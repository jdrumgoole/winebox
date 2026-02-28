"""Wine parser service for extracting structured data from OCR text."""

import logging
from typing import Any

from .extractors import (
    extract_alcohol,
    extract_classification,
    extract_country,
    extract_drink_window,
    extract_grape_blend,
    extract_grape_variety,
    extract_name,
    extract_producer_type,
    extract_region,
    extract_vintage,
    extract_wine_type,
    extract_winery,
)

logger = logging.getLogger(__name__)


class WineParserService:
    """Service for parsing wine information from OCR text."""

    def parse(self, text: str) -> dict[str, Any]:
        """Parse OCR text to extract wine information.

        Args:
            text: Raw OCR text from wine labels.

        Returns:
            Dictionary with extracted wine information.
        """
        result: dict[str, Any] = {}

        if not text:
            return result

        # Clean text
        text_clean = text.strip()

        # Extract vintage year
        vintage = extract_vintage(text_clean)
        if vintage:
            result["vintage"] = vintage

        # Extract alcohol percentage
        alcohol = extract_alcohol(text_clean)
        if alcohol:
            result["alcohol_percentage"] = alcohol

        # Extract grape variety
        grape = extract_grape_variety(text_clean)
        if grape:
            result["grape_variety"] = grape

        # Extract grape blend (multiple grapes with percentages)
        grape_blend = extract_grape_blend(text_clean)
        if grape_blend:
            result["grape_varieties"] = grape_blend

        # Extract region
        region = extract_region(text_clean)
        if region:
            result["region"] = region

        # Extract country
        country = extract_country(text_clean)
        if country:
            result["country"] = country

        # Try to extract winery name (usually at the top of front label)
        winery = extract_winery(text_clean)
        if winery:
            result["winery"] = winery

        # Try to extract wine name
        name = extract_name(text_clean, result)
        if name:
            result["name"] = name

        # Extract wine type (red, white, etc.)
        wine_type = extract_wine_type(text_clean, result)
        if wine_type:
            result["wine_type"] = wine_type

        # Extract classification
        classification = extract_classification(text_clean)
        if classification:
            result["classification"] = classification

        # Extract producer type
        producer_type = extract_producer_type(text_clean)
        if producer_type:
            result["producer_type"] = producer_type

        # Extract drink window
        drink_window = extract_drink_window(text_clean)
        if drink_window:
            result["drink_window_start"] = drink_window[0]
            result["drink_window_end"] = drink_window[1]

        return result
