"""Extraction functions for parsing wine information from text."""

import re
from typing import Any

from .constants import (
    CLASSIFICATION_DISPLAY_NAMES,
    CLASSIFICATION_PATTERNS,
    CLASSIFICATION_PRIORITY,
    GRAPE_VARIETIES,
    RED_GRAPES,
    REGION_TO_COUNTRY,
    WHITE_GRAPES,
    WINE_COUNTRIES,
    WINE_REGIONS,
    WINE_TYPE_INDICATORS,
)


def extract_vintage(text: str) -> int | None:
    """Extract vintage year from text."""
    # Look for 4-digit years between 1900 and current year + 2
    pattern = r"\b(19\d{2}|20[0-2]\d)\b"
    matches = re.findall(pattern, text)

    if matches:
        # Prefer years that look like vintages (not recent years like current year)
        for year_str in matches:
            year = int(year_str)
            if 1950 <= year <= 2025:
                return year

        # Fall back to first found year
        return int(matches[0])

    return None


def extract_alcohol(text: str) -> float | None:
    """Extract alcohol percentage from text."""
    # Various patterns for alcohol content
    patterns = [
        r"(\d{1,2}[.,]\d{1,2})\s*%\s*(?:vol|alc|alcohol|abv)?",
        r"(?:alc|alcohol|abv)[:\s]*(\d{1,2}[.,]\d{1,2})\s*%",
        r"(\d{1,2}[.,]\d{1,2})\s*%\s*vol",
        r"(\d{1,2})\s*%\s*(?:vol|alc|alcohol|abv)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).replace(",", ".")
            try:
                alcohol = float(value)
                if 5.0 <= alcohol <= 25.0:  # Reasonable wine alcohol range
                    return alcohol
            except ValueError:
                continue

    return None


def extract_grape_variety(text: str) -> str | None:
    """Extract grape variety from text."""
    text_lower = text.lower()

    for grape in GRAPE_VARIETIES:
        if grape.lower() in text_lower:
            return grape

    return None


def extract_region(text: str) -> str | None:
    """Extract wine region from text."""
    text_lower = text.lower()

    for region in WINE_REGIONS:
        if region.lower() in text_lower:
            return region

    return None


def extract_country(text: str) -> str | None:
    """Extract country from text."""
    text_lower = text.lower()

    # Direct country mentions
    for country in WINE_COUNTRIES:
        if country.lower() in text_lower:
            # Normalize some entries
            if country in ["California", "Oregon", "Washington"]:
                return "United States"
            if country == "USA":
                return "United States"
            return country

    # Infer from region if possible
    region = extract_region(text)
    if region:
        return REGION_TO_COUNTRY.get(region)

    return None


def extract_winery(text: str) -> str | None:
    """Extract winery name from text.

    Typically the winery name appears at the top of the label,
    often in larger text. This is a simple heuristic.
    """
    lines = text.strip().split("\n")

    # First non-empty line that's not a year or standard phrase
    for line in lines[:5]:  # Check first 5 lines
        line = line.strip()
        if not line:
            continue

        # Skip if it's just a year
        if re.match(r"^\d{4}$", line):
            continue

        # Skip if it's a common label phrase
        skip_phrases = [
            "product of",
            "produced by",
            "bottled by",
            "imported by",
            "contains sulfites",
            "alcohol",
            "estate",
            "reserve",
        ]
        if any(phrase in line.lower() for phrase in skip_phrases):
            continue

        # Skip if it looks like alcohol content
        if re.search(r"\d+[.,]?\d*\s*%", line):
            continue

        # If line has reasonable length, might be winery name
        if 3 <= len(line) <= 50:
            return line

    return None


def extract_name(text: str, parsed: dict[str, Any]) -> str | None:
    """Extract wine name from text.

    Often the wine name includes grape variety, region, or
    is a distinctive name on the label.
    """
    lines = text.strip().split("\n")

    # Try to find a distinctive wine name
    candidates = []

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Check if line could be a wine name
        # Skip very short or very long lines
        if len(line) < 3 or len(line) > 60:
            continue

        # Skip year-only lines
        if re.match(r"^\d{4}$", line):
            continue

        # Skip alcohol percentage lines
        if re.search(r"\d+[.,]?\d*\s*%", line):
            continue

        candidates.append(line)

    if candidates:
        # Prefer line with grape variety or vintage if present
        grape = parsed.get("grape_variety", "")
        vintage = parsed.get("vintage")

        for candidate in candidates:
            if grape and grape.lower() in candidate.lower():
                return candidate
            if vintage and str(vintage) in candidate:
                return candidate

        # Fall back to first candidate that's not the winery
        winery = parsed.get("winery", "")
        for candidate in candidates:
            if candidate != winery:
                return candidate

        return candidates[0] if candidates else None

    return None


def extract_wine_type(text: str, parsed: dict[str, Any]) -> str | None:
    """Extract wine type from text or infer from grape variety."""
    text_lower = text.lower()

    # Check for explicit wine type indicators
    for wine_type, indicators in WINE_TYPE_INDICATORS.items():
        for indicator in indicators:
            if indicator in text_lower:
                return wine_type

    # Try to infer from grape variety
    grape = parsed.get("grape_variety", "").lower()
    if grape:
        for red_grape in RED_GRAPES:
            if red_grape in grape:
                return "red"
        for white_grape in WHITE_GRAPES:
            if white_grape in grape:
                return "white"

    return None


def extract_classification(text: str) -> str | None:
    """Extract wine classification from text."""
    text_lower = text.lower()

    # Check patterns in order of specificity
    for classification_key in CLASSIFICATION_PRIORITY:
        patterns = CLASSIFICATION_PATTERNS.get(classification_key, [])
        for pattern in patterns:
            if pattern in text_lower:
                return CLASSIFICATION_DISPLAY_NAMES.get(
                    classification_key, classification_key
                )

    return None


def extract_grape_blend(text: str) -> list[dict[str, Any]] | None:
    """Extract grape blend with percentages from text.

    Looks for patterns like:
    - "70% Cabernet Sauvignon, 30% Merlot"
    - "Cabernet Sauvignon 60%, Merlot 40%"
    """
    blend: list[dict[str, Any]] = []

    # Pattern: percentage before grape
    pattern1 = r"(\d{1,3})\s*%\s*([A-Za-z][A-Za-z\s\''-]+)"
    matches1 = re.findall(pattern1, text)

    for pct, grape_text in matches1:
        grape_clean = grape_text.strip().rstrip(",;")
        # Check if it's a known grape
        for grape in GRAPE_VARIETIES:
            if grape.lower() in grape_clean.lower():
                blend.append({"name": grape, "percentage": int(pct)})
                break

    # Pattern: grape before percentage
    pattern2 = r"([A-Za-z][A-Za-z\s\''-]+)\s+(\d{1,3})\s*%"
    matches2 = re.findall(pattern2, text)

    for grape_text, pct in matches2:
        grape_clean = grape_text.strip()
        # Check if it's a known grape and not already added
        for grape in GRAPE_VARIETIES:
            if grape.lower() in grape_clean.lower():
                if not any(b["name"] == grape for b in blend):
                    blend.append({"name": grape, "percentage": int(pct)})
                break

    return blend if blend else None


def extract_producer_type(text: str) -> str | None:
    """Extract producer type from text."""
    text_lower = text.lower()

    # Estate indicators
    estate_indicators = [
        "estate bottled", "estate grown", "estate produced",
        "mis en bouteille au château", "mis en bouteille au domaine",
        "erzeugerabfüllung", "gutsabfüllung",
        "imbottigliato all'origine", "imbottigliato dal produttore",
    ]

    for indicator in estate_indicators:
        if indicator in text_lower:
            return "estate"

    # Negociant indicators
    negociant_indicators = [
        "négociant", "negociant", "selected by", "bottled by",
        "mis en bouteille par", "elevé par",
    ]

    for indicator in negociant_indicators:
        if indicator in text_lower:
            return "negociant"

    # Cooperative indicators
    coop_indicators = [
        "cooperative", "coopérative", "cantina sociale",
        "bodega cooperativa", "cave coopérative",
    ]

    for indicator in coop_indicators:
        if indicator in text_lower:
            return "cooperative"

    return None


def extract_drink_window(text: str) -> tuple[int, int] | None:
    """Extract drink window (recommended drinking years) from text.

    Looks for patterns like:
    - "Drink 2025-2040"
    - "Best 2020-2035"
    - "Optimal drinking: 2022-2030"
    """
    # Pattern for year ranges
    patterns = [
        r"(?:drink|best|optimal|drinking)[:\s]+(\d{4})\s*[-–]\s*(\d{4})",
        r"(\d{4})\s*[-–]\s*(\d{4})\s*(?:drinking|drink)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                start_year = int(match.group(1))
                end_year = int(match.group(2))
                if 2000 <= start_year <= 2100 and 2000 <= end_year <= 2100:
                    return (start_year, end_year)
            except (ValueError, IndexError):
                continue

    return None
