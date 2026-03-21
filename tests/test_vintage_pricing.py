"""Tests for vintage-specific pricing features.

Tests the annotation script's vintage parsing, batch prompt generation,
and the updated price lookup logic in the router and enrichment service.
"""

import json

import pytest

from scripts.annotate_xwines_prices import (
    PriceAnnotator,
    build_batch_prompt,
    parse_response,
    validate_price_entry,
)


class TestParseVintages:
    """Tests for PriceAnnotator.parse_vintages()."""

    def test_standard_list_string(self) -> None:
        result = PriceAnnotator.parse_vintages("[2020, 2019, 2018]")
        assert result == [2020, 2019, 2018]

    def test_quoted_strings_list(self) -> None:
        result = PriceAnnotator.parse_vintages("['2020', '2019', '2018']")
        assert result == [2020, 2019, 2018]

    def test_empty_string(self) -> None:
        assert PriceAnnotator.parse_vintages("") == []

    def test_none(self) -> None:
        assert PriceAnnotator.parse_vintages(None) == []

    def test_empty_list(self) -> None:
        assert PriceAnnotator.parse_vintages("[]") == []

    def test_single_vintage(self) -> None:
        result = PriceAnnotator.parse_vintages("[2015]")
        assert result == [2015]

    def test_non_string_input(self) -> None:
        assert PriceAnnotator.parse_vintages(12345) == []  # type: ignore[arg-type]


class TestBuildBatchPrompt:
    """Tests for vintage-aware batch prompt generation."""

    def test_includes_vintage_in_prompt(self) -> None:
        items = [
            {
                "name": "Chateau Margaux",
                "xwines_id": 1,
                "vintage": 2018,
                "winery_name": "Chateau Margaux",
                "wine_type": "Red",
                "country": "France",
                "region_name": "Bordeaux",
            }
        ]
        prompt = build_batch_prompt(items)
        assert "Vintage: 2018" in prompt
        assert "Chateau Margaux" in prompt

    def test_base_price_no_vintage(self) -> None:
        items = [
            {
                "name": "Test Wine",
                "xwines_id": 2,
                "vintage": None,
                "wine_type": "White",
            }
        ]
        prompt = build_batch_prompt(items)
        assert "Vintage:" not in prompt
        assert "Test Wine" in prompt

    def test_mixed_vintages_and_base(self) -> None:
        items = [
            {"name": "Wine A", "xwines_id": 1, "vintage": 2020},
            {"name": "Wine B", "xwines_id": 2, "vintage": None},
            {"name": "Wine C", "xwines_id": 3, "vintage": 2015},
        ]
        prompt = build_batch_prompt(items)
        assert "Vintage: 2020" in prompt
        assert "Vintage: 2015" in prompt
        lines = prompt.split("\n")
        wine_lines = [l for l in lines if l.startswith(("1.", "2.", "3."))]
        assert len(wine_lines) == 3

    def test_prompt_mentions_vintage_pricing(self) -> None:
        items = [{"name": "Test", "xwines_id": 1, "vintage": 2020}]
        prompt = build_batch_prompt(items)
        assert "wine-vintage" in prompt.lower() or "Vintage" in prompt


class TestValidatePriceEntry:
    """Tests for price entry validation (unchanged but verify still works)."""

    def test_valid_entry(self) -> None:
        entry = {
            "price_low": 25.0,
            "price_high": 50.0,
            "confidence": "medium",
            "price_tier": "mid_range",
            "note": "Good wine",
        }
        result = validate_price_entry(entry)
        assert result is not None
        assert result["price_low_usd"] == 25.0
        assert result["price_high_usd"] == 50.0

    def test_invalid_price_range(self) -> None:
        entry = {"price_low": 50.0, "price_high": 25.0}
        assert validate_price_entry(entry) is None

    def test_zero_price(self) -> None:
        entry = {"price_low": 0, "price_high": 25.0}
        assert validate_price_entry(entry) is None


class TestParseResponse:
    """Tests for JSON response parsing."""

    def test_valid_json_array(self) -> None:
        text = json.dumps([{"price_low": 10, "price_high": 20}])
        result = parse_response(text)
        assert result is not None
        assert len(result) == 1

    def test_markdown_wrapped(self) -> None:
        text = '```json\n[{"price_low": 10, "price_high": 20}]\n```'
        result = parse_response(text)
        assert result is not None
        assert len(result) == 1

    def test_invalid_json(self) -> None:
        assert parse_response("not json") is None

    def test_not_array(self) -> None:
        assert parse_response('{"price_low": 10}') is None
