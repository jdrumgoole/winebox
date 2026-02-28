"""Regression tests for table view layout fix.

The cellar and X-Wines table views must remove the 'wine-grid' CSS class
from their container so the table gets full width instead of being
constrained by the CSS grid layout (which is designed for card view).

These tests read the JS source to verify the fix is present.
"""

from pathlib import Path

import pytest

APP_JS = Path(__file__).parent.parent / "winebox" / "static" / "js" / "app.js"


@pytest.fixture(scope="module")
def app_js_source() -> str:
    """Read the app.js source once for all tests in this module."""
    return APP_JS.read_text()


def test_cellar_table_view_removes_wine_grid_class(app_js_source: str) -> None:
    """Cellar table mode must remove wine-grid class for full-width layout."""
    assert "cellar-list" in app_js_source
    # The setCellarViewMode function should remove wine-grid in table mode
    assert "classList.remove('wine-grid')" in app_js_source


def test_cellar_card_view_restores_wine_grid_class(app_js_source: str) -> None:
    """Cellar card mode must restore wine-grid class for grid layout."""
    assert "classList.add('wine-grid')" in app_js_source


def test_xwines_table_view_removes_wine_grid_class(app_js_source: str) -> None:
    """X-Wines table mode must remove wine-grid class for full-width layout."""
    assert "xwines-results" in app_js_source
    # The setXWinesViewMode function should also toggle wine-grid
    # Verify there are at least 2 occurrences (cellar + xwines)
    remove_count = app_js_source.count("classList.remove('wine-grid')")
    assert remove_count >= 2, (
        f"Expected wine-grid removal in both cellar and xwines, found {remove_count}"
    )


def test_wine_table_has_full_width_css() -> None:
    """The .wine-table CSS must set width: 100% for proper table display."""
    css_path = Path(__file__).parent.parent / "winebox" / "static" / "css" / "style.css"
    css_source = css_path.read_text()
    # Verify the table has width: 100%
    assert ".wine-table" in css_source
    assert "width: 100%" in css_source
