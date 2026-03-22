"""Tests for demo/sample data definitions and configuration."""

import pytest

from winebox.routers.demo import (
    DEMO_TAG,
    DEMO_WINE_COUNT,
    _CHECKOUT_NOTES,
    _TYPE_MAP,
    _TYPE_TARGETS,
    _parse_grapes,
    _parse_vintages,
)


class TestDemoConfig:
    """Tests for demo data configuration."""

    def test_demo_tag(self) -> None:
        assert DEMO_TAG == {"_demo": "true"}

    def test_wine_count(self) -> None:
        assert DEMO_WINE_COUNT == 500

    def test_type_targets_sum_to_count(self) -> None:
        total = sum(_TYPE_TARGETS.values())
        assert total == DEMO_WINE_COUNT, (
            f"Type targets sum to {total}, expected {DEMO_WINE_COUNT}"
        )

    def test_all_type_targets_have_mapping(self) -> None:
        for wine_type in _TYPE_TARGETS:
            assert wine_type in _TYPE_MAP, f"No mapping for type '{wine_type}'"

    def test_checkout_notes_not_empty(self) -> None:
        assert len(_CHECKOUT_NOTES) >= 10


class TestParseGrapes:
    """Tests for _parse_grapes helper."""

    def test_python_list(self) -> None:
        assert _parse_grapes("['Merlot', 'Cabernet Sauvignon']") == "Merlot"

    def test_plain_string(self) -> None:
        assert _parse_grapes("Pinot Noir") == "Pinot Noir"

    def test_none(self) -> None:
        assert _parse_grapes(None) is None

    def test_empty(self) -> None:
        assert _parse_grapes("") is None

    def test_empty_list(self) -> None:
        assert _parse_grapes("[]") is None


class TestParseVintages:
    """Tests for _parse_vintages helper."""

    def test_standard_list(self) -> None:
        assert _parse_vintages("[2020, 2019, 2018]") == [2020, 2019, 2018]

    def test_string_list(self) -> None:
        assert _parse_vintages("['2020', '2019']") == [2020, 2019]

    def test_none(self) -> None:
        assert _parse_vintages(None) == []

    def test_empty(self) -> None:
        assert _parse_vintages("") == []

    def test_empty_list(self) -> None:
        assert _parse_vintages("[]") == []
