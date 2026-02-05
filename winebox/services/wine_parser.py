"""Wine parser service for extracting structured data from OCR text."""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Common grape varieties
GRAPE_VARIETIES = [
    "Cabernet Sauvignon",
    "Cabernet",
    "Merlot",
    "Pinot Noir",
    "Pinot Grigio",
    "Pinot Gris",
    "Chardonnay",
    "Sauvignon Blanc",
    "Riesling",
    "Syrah",
    "Shiraz",
    "Zinfandel",
    "Malbec",
    "Tempranillo",
    "Sangiovese",
    "Nebbiolo",
    "Grenache",
    "Garnacha",
    "Mourvedre",
    "Viognier",
    "Gewurztraminer",
    "Chenin Blanc",
    "Semillon",
    "Muscat",
    "Moscato",
    "Prosecco",
    "Champagne",
    "Cava",
    "Albarino",
    "Gruner Veltliner",
    "Torrontes",
    "Verdejo",
    "Carmenere",
    "Petite Sirah",
    "Petit Verdot",
    "Barbera",
    "Primitivo",
    "Montepulciano",
    "Nero d'Avola",
    "Vermentino",
    "Fiano",
    "Trebbiano",
    "Corvina",
    "Gamay",
    "Beaujolais",
]

# Common wine regions
WINE_REGIONS = [
    # France
    "Bordeaux",
    "Burgundy",
    "Bourgogne",
    "Champagne",
    "Rhone",
    "Loire",
    "Alsace",
    "Provence",
    "Languedoc",
    "Cotes du Rhone",
    "Medoc",
    "Saint-Emilion",
    "Pauillac",
    "Margaux",
    "Chablis",
    "Beaune",
    "Sancerre",
    "Pouilly-Fume",
    # Italy
    "Tuscany",
    "Toscana",
    "Piedmont",
    "Piemonte",
    "Veneto",
    "Sicily",
    "Sicilia",
    "Chianti",
    "Barolo",
    "Barbaresco",
    "Brunello di Montalcino",
    "Montalcino",
    "Valpolicella",
    "Amarone",
    "Prosecco",
    "Friuli",
    # Spain
    "Rioja",
    "Ribera del Duero",
    "Priorat",
    "Rias Baixas",
    "Rueda",
    "Navarra",
    "La Mancha",
    "Jerez",
    "Sherry",
    # USA
    "Napa Valley",
    "Napa",
    "Sonoma",
    "Willamette Valley",
    "Paso Robles",
    "Santa Barbara",
    "Russian River",
    "Alexander Valley",
    "Central Coast",
    "Oregon",
    "Washington",
    # Other
    "Marlborough",
    "Mendoza",
    "Stellenbosch",
    "Mosel",
    "Rheingau",
    "Pfalz",
    "Douro",
    "Alentejo",
    "Barossa Valley",
    "Hunter Valley",
    "Margaret River",
    "Hawke's Bay",
    "Maipo Valley",
    "Colchagua",
    "Casablanca",
]

# Countries commonly associated with wine
WINE_COUNTRIES = [
    "France",
    "Italy",
    "Spain",
    "Portugal",
    "Germany",
    "Austria",
    "United States",
    "USA",
    "California",
    "Oregon",
    "Washington",
    "Australia",
    "New Zealand",
    "Argentina",
    "Chile",
    "South Africa",
    "Greece",
    "Lebanon",
    "Israel",
    "Canada",
    "Hungary",
    "Romania",
    "Georgia",
    "Slovenia",
    "Croatia",
]


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
        text_upper = text_clean.upper()
        text_lower = text_clean.lower()

        # Extract vintage year
        vintage = self._extract_vintage(text_clean)
        if vintage:
            result["vintage"] = vintage

        # Extract alcohol percentage
        alcohol = self._extract_alcohol(text_clean)
        if alcohol:
            result["alcohol_percentage"] = alcohol

        # Extract grape variety
        grape = self._extract_grape_variety(text_clean)
        if grape:
            result["grape_variety"] = grape

        # Extract region
        region = self._extract_region(text_clean)
        if region:
            result["region"] = region

        # Extract country
        country = self._extract_country(text_clean)
        if country:
            result["country"] = country

        # Try to extract winery name (usually at the top of front label)
        winery = self._extract_winery(text_clean)
        if winery:
            result["winery"] = winery

        # Try to extract wine name
        name = self._extract_name(text_clean, result)
        if name:
            result["name"] = name

        return result

    def _extract_vintage(self, text: str) -> int | None:
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

    def _extract_alcohol(self, text: str) -> float | None:
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

    def _extract_grape_variety(self, text: str) -> str | None:
        """Extract grape variety from text."""
        text_lower = text.lower()

        for grape in GRAPE_VARIETIES:
            if grape.lower() in text_lower:
                return grape

        return None

    def _extract_region(self, text: str) -> str | None:
        """Extract wine region from text."""
        text_lower = text.lower()

        for region in WINE_REGIONS:
            if region.lower() in text_lower:
                return region

        return None

    def _extract_country(self, text: str) -> str | None:
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
        region = self._extract_region(text)
        if region:
            region_to_country = {
                "Bordeaux": "France",
                "Burgundy": "France",
                "Champagne": "France",
                "Tuscany": "Italy",
                "Piedmont": "Italy",
                "Rioja": "Spain",
                "Napa Valley": "United States",
                "Marlborough": "New Zealand",
                "Mendoza": "Argentina",
                "Barossa Valley": "Australia",
            }
            return region_to_country.get(region)

        return None

    def _extract_winery(self, text: str) -> str | None:
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

    def _extract_name(self, text: str, parsed: dict) -> str | None:
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
