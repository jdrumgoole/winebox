"""Wine parser service for extracting structured data from OCR text."""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Wine type indicators
WINE_TYPE_INDICATORS = {
    "red": [
        "red wine", "vin rouge", "vino rosso", "vino tinto", "rotwein",
        "cabernet", "merlot", "pinot noir", "syrah", "shiraz", "malbec",
        "sangiovese", "nebbiolo", "tempranillo", "zinfandel", "primitivo",
    ],
    "white": [
        "white wine", "vin blanc", "vino bianco", "vino blanco", "weisswein",
        "chardonnay", "sauvignon blanc", "riesling", "pinot grigio", "pinot gris",
        "gewurztraminer", "viognier", "chenin blanc", "semillon", "gruner veltliner",
    ],
    "rosé": [
        "rosé", "rose", "rosado", "rosato", "vin rosé",
        "white zinfandel", "blush",
    ],
    "sparkling": [
        "sparkling", "champagne", "prosecco", "cava", "crémant", "cremant",
        "spumante", "sekt", "méthode traditionnelle", "brut", "extra brut",
        "demi-sec", "mousseux",
    ],
    "fortified": [
        "fortified", "port", "porto", "sherry", "jerez", "madeira",
        "marsala", "vermouth", "vin doux naturel",
    ],
    "dessert": [
        "dessert wine", "late harvest", "ice wine", "eiswein", "vin santo",
        "sauternes", "barsac", "tokaji", "trockenbeerenauslese", "beerenauslese",
        "passito", "recioto",
    ],
}

# Classification patterns by country/system
CLASSIFICATION_PATTERNS = {
    # France
    "grand_cru": ["grand cru", "grand cru classé"],
    "premier_cru": ["premier cru", "1er cru", "premier cru classé"],
    "cru_classe": ["cru classé", "cru classe", "classé growth"],
    "cru_bourgeois": ["cru bourgeois"],
    "aoc_aop": ["aoc", "aop", "appellation", "contrôlée", "controlee", "protégée"],
    "igp": ["igp", "vin de pays"],
    # Italy
    "docg": ["docg", "denominazione di origine controllata e garantita"],
    "doc": ["doc", "denominazione di origine controllata"],
    "igt": ["igt", "indicazione geografica tipica"],
    "riserva": ["riserva"],
    "superiore": ["superiore"],
    # Spain
    "doca": ["doca", "denominación de origen calificada"],
    "do": ["denominación de origen", "d.o."],
    "gran_reserva": ["gran reserva"],
    "reserva": ["reserva"],
    "crianza": ["crianza"],
    "joven": ["joven"],
    # Germany
    "grosses_gewachs": ["grosses gewächs", "grosses gewachs", "gg"],
    "erstes_gewachs": ["erstes gewächs", "erstes gewachs"],
    "trockenbeerenauslese": ["trockenbeerenauslese", "tba"],
    "beerenauslese": ["beerenauslese", "ba"],
    "auslese": ["auslese"],
    "spatlese": ["spätlese", "spatlese"],
    "kabinett": ["kabinett"],
    # USA/General
    "estate_bottled": ["estate bottled", "estate grown", "estate produced"],
    "reserve": ["reserve", "reserva"],
}

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

        # Extract grape blend (multiple grapes with percentages)
        grape_blend = self._extract_grape_blend(text_clean)
        if grape_blend:
            result["grape_varieties"] = grape_blend

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

        # Extract wine type (red, white, etc.)
        wine_type = self._extract_wine_type(text_clean, result)
        if wine_type:
            result["wine_type"] = wine_type

        # Extract classification
        classification = self._extract_classification(text_clean)
        if classification:
            result["classification"] = classification

        # Extract producer type
        producer_type = self._extract_producer_type(text_clean)
        if producer_type:
            result["producer_type"] = producer_type

        # Extract drink window
        drink_window = self._extract_drink_window(text_clean)
        if drink_window:
            result["drink_window_start"] = drink_window[0]
            result["drink_window_end"] = drink_window[1]

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

    def _extract_wine_type(self, text: str, parsed: dict) -> str | None:
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
            red_grapes = [
                "cabernet", "merlot", "pinot noir", "syrah", "shiraz", "malbec",
                "sangiovese", "nebbiolo", "tempranillo", "zinfandel", "primitivo",
                "barbera", "grenache", "mourvedre", "gamay",
            ]
            white_grapes = [
                "chardonnay", "sauvignon blanc", "riesling", "pinot grigio",
                "gewurztraminer", "viognier", "chenin blanc", "semillon",
                "gruner veltliner", "albarino", "verdejo",
            ]

            for red_grape in red_grapes:
                if red_grape in grape:
                    return "red"
            for white_grape in white_grapes:
                if white_grape in grape:
                    return "white"

        return None

    def _extract_classification(self, text: str) -> str | None:
        """Extract wine classification from text."""
        text_lower = text.lower()

        # Check patterns in order of specificity
        # More specific classifications first
        priority_order = [
            "trockenbeerenauslese", "beerenauslese", "auslese", "spatlese", "kabinett",
            "grosses_gewachs", "erstes_gewachs",
            "grand_cru", "premier_cru", "cru_classe", "cru_bourgeois",
            "docg", "doc", "igt", "riserva", "superiore",
            "doca", "gran_reserva", "reserva", "crianza", "joven",
            "aoc_aop", "igp",
            "estate_bottled", "reserve",
        ]

        for classification_key in priority_order:
            patterns = CLASSIFICATION_PATTERNS.get(classification_key, [])
            for pattern in patterns:
                if pattern in text_lower:
                    # Return the display-friendly version
                    display_names = {
                        "grand_cru": "Grand Cru",
                        "premier_cru": "Premier Cru",
                        "cru_classe": "Cru Classé",
                        "cru_bourgeois": "Cru Bourgeois",
                        "aoc_aop": "AOC/AOP",
                        "igp": "IGP",
                        "docg": "DOCG",
                        "doc": "DOC",
                        "igt": "IGT",
                        "riserva": "Riserva",
                        "superiore": "Superiore",
                        "doca": "DOCa",
                        "gran_reserva": "Gran Reserva",
                        "reserva": "Reserva",
                        "crianza": "Crianza",
                        "joven": "Joven",
                        "grosses_gewachs": "Grosses Gewächs",
                        "erstes_gewachs": "Erstes Gewächs",
                        "trockenbeerenauslese": "Trockenbeerenauslese",
                        "beerenauslese": "Beerenauslese",
                        "auslese": "Auslese",
                        "spatlese": "Spätlese",
                        "kabinett": "Kabinett",
                        "estate_bottled": "Estate Bottled",
                        "reserve": "Reserve",
                    }
                    return display_names.get(classification_key, classification_key)

        return None

    def _extract_grape_blend(self, text: str) -> list[dict[str, Any]] | None:
        """Extract grape blend with percentages from text.

        Looks for patterns like:
        - "70% Cabernet Sauvignon, 30% Merlot"
        - "Cabernet Sauvignon 60%, Merlot 40%"
        """
        text_lower = text.lower()
        blend = []

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

    def _extract_producer_type(self, text: str) -> str | None:
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

    def _extract_drink_window(self, text: str) -> tuple[int, int] | None:
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
