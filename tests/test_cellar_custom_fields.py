"""Tests for displaying additional & custom fields in the Cellar view.

Card view should show custom_fields as distinctly-styled tags.
Table view should have expandable detail rows with all additional + custom fields.

Static tests read JS/CSS source to verify expected code patterns.
API integration test verifies custom_fields round-trip through the API.
"""

import io
import json
from pathlib import Path

import pytest
from httpx import AsyncClient

APP_JS = Path(__file__).parent.parent / "winebox" / "static" / "js" / "app.js"
STYLE_CSS = Path(__file__).parent.parent / "winebox" / "static" / "css" / "style.css"


@pytest.fixture(scope="module")
def app_js_source() -> str:
    """Read the app.js source once for all tests in this module."""
    return APP_JS.read_text()


@pytest.fixture(scope="module")
def style_css_source() -> str:
    """Read the style.css source once for all tests in this module."""
    return STYLE_CSS.read_text()


# --- Static JS source tests (card view) ---


def test_card_view_renders_custom_fields(app_js_source: str) -> None:
    """renderWineGrid must render custom_fields as tags with wine-tag-custom class."""
    assert "wine.custom_fields" in app_js_source
    assert "wine-tag-custom" in app_js_source


def test_card_view_renders_additional_standard_fields(app_js_source: str) -> None:
    """renderWineGrid must reference sub_region, alcohol_percentage, and notes."""
    assert "wine.sub_region" in app_js_source
    assert "wine.alcohol_percentage" in app_js_source
    assert "wine.notes" in app_js_source


# --- Static JS source tests (table view) ---


def test_table_view_has_expandable_detail_row(app_js_source: str) -> None:
    """renderCellarTable must contain the wine-table-detail-row class."""
    assert "wine-table-detail-row" in app_js_source


def test_table_detail_row_shows_custom_fields(app_js_source: str) -> None:
    """The table detail row must render custom_fields as key-value pairs."""
    # The additionalFields building code references wine.custom_fields
    assert "wine.custom_fields" in app_js_source
    assert "wine-table-detail-content" in app_js_source


def test_table_detail_row_shows_additional_standard_fields(app_js_source: str) -> None:
    """The table detail row must reference all additional standard fields."""
    for field in ["sub_region", "appellation", "classification",
                  "alcohol_percentage", "wine_type", "price_tier", "notes"]:
        assert f"wine.{field}" in app_js_source, f"Missing field: wine.{field}"


def test_table_expand_chevron_exists(app_js_source: str) -> None:
    """The table must have a wine-table-expand chevron element."""
    assert "wine-table-expand" in app_js_source


# --- Static JS source tests (card expand/collapse) ---


def test_card_view_has_expand_button(app_js_source: str) -> None:
    """Card view must have a wine-card-expand-btn element for toggling extra tags."""
    assert "wine-card-expand-btn" in app_js_source


def test_card_view_extra_tags_hidden_by_default(app_js_source: str) -> None:
    """Card view must wrap extra tags in a wine-card-extra div."""
    assert "wine-card-extra" in app_js_source


# --- Static CSS source tests ---


def test_detail_modal_compact_layout_css(style_css_source: str) -> None:
    """CSS must define .wine-detail-fields grid wrapper and .wine-detail-field with background."""
    assert ".wine-detail-field" in style_css_source
    assert ".wine-detail-fields" in style_css_source
    # Verify grid layout on the wrapper
    import re
    match = re.search(
        r"\.wine-detail-fields\s*\{[^}]*display:\s*grid",
        style_css_source,
    )
    assert match is not None, ".wine-detail-fields should have display: grid"


def test_detail_modal_custom_fields_grid_css(style_css_source: str) -> None:
    """CSS must define .wine-detail-custom-fields for grid layout."""
    assert ".wine-detail-custom-fields" in style_css_source


def test_custom_tag_css_exists(style_css_source: str) -> None:
    """CSS must define .wine-tag-custom rule."""
    assert ".wine-tag-custom" in style_css_source


def test_detail_row_css_exists(style_css_source: str) -> None:
    """CSS must define .wine-table-detail-row and .wine-table-detail-row.expanded rules."""
    assert ".wine-table-detail-row" in style_css_source
    assert ".wine-table-detail-row.expanded" in style_css_source


def test_expand_chevron_css_exists(style_css_source: str) -> None:
    """CSS must define .wine-table-expand rule."""
    assert ".wine-table-expand" in style_css_source


# --- API integration test ---


@pytest.mark.asyncio
async def test_wine_api_returns_custom_fields(
    client: AsyncClient, sample_image_bytes: bytes
) -> None:
    """Checkin a wine with custom_fields, then GET it and verify they're returned."""
    custom = {"Provenance": "Private cellar", "Condition": "Excellent"}

    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Custom Fields Test Wine",
        "quantity": "1",
        "custom_fields": json.dumps(custom),
    }

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    wine_id = wine["id"]
    assert wine["custom_fields"]["Provenance"] == "Private cellar"
    assert wine["custom_fields"]["Condition"] == "Excellent"

    # GET the wine back and verify custom_fields persist
    get_response = await client.get(f"/api/wines/{wine_id}")
    assert get_response.status_code == 200

    fetched = get_response.json()
    assert fetched["custom_fields"]["Provenance"] == "Private cellar"
    assert fetched["custom_fields"]["Condition"] == "Excellent"
