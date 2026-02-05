"""Tests for OCR and wine parsing services."""

import pytest

from winebox.services.wine_parser import WineParserService


class TestWineParserService:
    """Tests for WineParserService."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.parser = WineParserService()

    def test_parse_empty_text(self) -> None:
        """Test parsing empty text."""
        result = self.parser.parse("")
        assert result == {}

    def test_parse_vintage(self) -> None:
        """Test parsing vintage year."""
        result = self.parser.parse("Estate Reserve 2019")
        assert result.get("vintage") == 2019

    def test_parse_vintage_various_positions(self) -> None:
        """Test parsing vintage in various positions."""
        texts = [
            "2018 Cabernet Sauvignon",
            "Chardonnay 2020",
            "Vintage 2019 Reserve",
        ]
        expected_vintages = [2018, 2020, 2019]

        for text, expected in zip(texts, expected_vintages):
            result = self.parser.parse(text)
            assert result.get("vintage") == expected

    def test_parse_alcohol_percentage(self) -> None:
        """Test parsing alcohol percentage."""
        texts = [
            "13.5% vol",
            "Alcohol 14.0%",
            "ABV: 12.5%",
            "14% Alc/Vol",
        ]
        expected = [13.5, 14.0, 12.5, 14.0]

        for text, exp in zip(texts, expected):
            result = self.parser.parse(text)
            assert result.get("alcohol_percentage") == exp

    def test_parse_grape_variety(self) -> None:
        """Test parsing grape varieties."""
        texts = [
            "Cabernet Sauvignon",
            "100% Merlot",
            "Pinot Noir from Oregon",
            "Estate Grown Chardonnay",
        ]
        expected_grapes = [
            "Cabernet Sauvignon",
            "Merlot",
            "Pinot Noir",
            "Chardonnay",
        ]

        for text, expected in zip(texts, expected_grapes):
            result = self.parser.parse(text)
            assert result.get("grape_variety") == expected

    def test_parse_region(self) -> None:
        """Test parsing wine regions."""
        texts = [
            "Napa Valley",
            "From the heart of Bordeaux",
            "Sonoma County",
            "Produced in Burgundy",
        ]
        expected_regions = ["Napa Valley", "Bordeaux", "Sonoma", "Burgundy"]

        for text, expected in zip(texts, expected_regions):
            result = self.parser.parse(text)
            assert result.get("region") == expected

    def test_parse_country(self) -> None:
        """Test parsing countries."""
        texts = [
            "Product of France",
            "Product of Italy",
            "Made in USA",
            "Imported from Spain",
        ]
        expected_countries = ["France", "Italy", "United States", "Spain"]

        for text, expected in zip(texts, expected_countries):
            result = self.parser.parse(text)
            assert result.get("country") == expected

    def test_parse_full_label(self) -> None:
        """Test parsing a full wine label."""
        text = """
        CHATEAU MARGAUX
        2016
        Grand Vin de Bordeaux
        MARGAUX
        Appellation Margaux Controlee
        13.5% vol
        Product of France
        """

        result = self.parser.parse(text)

        assert result.get("vintage") == 2016
        assert result.get("alcohol_percentage") == 13.5
        assert result.get("region") == "Bordeaux"
        assert result.get("country") == "France"

    def test_parse_california_wine_label(self) -> None:
        """Test parsing a California wine label."""
        text = """
        OPUS ONE
        2018
        Napa Valley
        Red Wine
        Cabernet Sauvignon
        14.5% Alc. by Vol.
        """

        result = self.parser.parse(text)

        assert result.get("vintage") == 2018
        assert result.get("alcohol_percentage") == 14.5
        assert result.get("grape_variety") == "Cabernet Sauvignon"
        assert result.get("region") == "Napa Valley"

    def test_parse_no_vintage_filter_current_year(self) -> None:
        """Test that very recent years are not used as vintage."""
        # Years like 2026 shouldn't be considered valid vintages for most wines
        result = self.parser.parse("Wine 2030")
        assert result.get("vintage") is None

    def test_parse_handles_malformed_text(self) -> None:
        """Test parsing handles malformed OCR text gracefully."""
        text = "W1ne N@me 2O19 C@bernet"  # OCR errors
        # Should not raise exception
        result = self.parser.parse(text)
        assert isinstance(result, dict)

    def test_country_inference_from_region(self) -> None:
        """Test country inference from known regions."""
        texts_and_expected = [
            ("Napa Valley Reserve", "United States"),
            ("Chianti Classico", None),  # Chianti not in regions list
            ("Bordeaux Grand Cru", "France"),
            ("Barossa Valley Estate", "Australia"),
        ]

        for text, expected_country in texts_and_expected:
            result = self.parser.parse(text)
            if expected_country:
                assert result.get("country") == expected_country
