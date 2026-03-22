"""Tests for demo/sample data install and removal."""

import pytest

from winebox.routers.demo import DEMO_TAG, SAMPLE_WINES, _CHECKOUTS


class TestDemoDataDefinitions:
    """Tests for the sample wine data definitions."""

    def test_sample_wines_not_empty(self) -> None:
        assert len(SAMPLE_WINES) > 0

    def test_all_wines_have_required_fields(self) -> None:
        required = {"name", "winery", "country", "wine_type_id", "quantity"}
        for wine in SAMPLE_WINES:
            missing = required - set(wine.keys())
            assert not missing, f"{wine['name']} missing fields: {missing}"

    def test_all_wine_types_represented(self) -> None:
        types = {w["wine_type_id"] for w in SAMPLE_WINES}
        expected = {"red", "white", "rose", "sparkling", "fortified", "dessert"}
        assert types == expected, f"Missing types: {expected - types}"

    def test_multiple_countries(self) -> None:
        countries = {w["country"] for w in SAMPLE_WINES}
        assert len(countries) >= 5, f"Only {len(countries)} countries"

    def test_multiple_price_tiers(self) -> None:
        tiers = {w.get("price_tier") for w in SAMPLE_WINES if w.get("price_tier")}
        assert len(tiers) >= 4, f"Only {len(tiers)} price tiers"

    def test_checkout_wines_exist_in_samples(self) -> None:
        sample_names = {w["name"] for w in SAMPLE_WINES}
        for name in _CHECKOUTS:
            assert name in sample_names, f"Checkout wine '{name}' not in samples"

    def test_checkout_quantities_valid(self) -> None:
        wine_quantities = {w["name"]: w["quantity"] for w in SAMPLE_WINES}
        for name, (qty, _notes) in _CHECKOUTS.items():
            assert qty < wine_quantities[name], (
                f"Checkout {qty} >= stock {wine_quantities[name]} for '{name}'"
            )

    def test_all_quantities_positive(self) -> None:
        for wine in SAMPLE_WINES:
            assert wine["quantity"] > 0, f"{wine['name']} has quantity 0"

    def test_demo_tag_is_consistent(self) -> None:
        assert DEMO_TAG == {"_demo": "true"}

    def test_all_vintages_reasonable(self) -> None:
        for wine in SAMPLE_WINES:
            v = wine.get("vintage")
            if v is not None:
                assert 1900 <= v <= 2030, f"{wine['name']} vintage {v} out of range"

    def test_all_prices_reasonable(self) -> None:
        for wine in SAMPLE_WINES:
            low = wine.get("estimated_price_low")
            high = wine.get("estimated_price_high")
            if low and high:
                assert low > 0, f"{wine['name']} price_low <= 0"
                assert high > low, f"{wine['name']} price_high <= price_low"
                assert high < 10000, f"{wine['name']} price_high unreasonably high"

    def test_unique_wine_names(self) -> None:
        names = [w["name"] for w in SAMPLE_WINES]
        assert len(names) == len(set(names)), "Duplicate wine names in demo data"
