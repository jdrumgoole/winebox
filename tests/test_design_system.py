"""Tests for the /design-system reference page."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_design_system_serves_page(client: AsyncClient) -> None:
    """/design-system returns the showcase HTML."""
    response = await client.get("/design-system")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_design_system_page_content(client: AsyncClient) -> None:
    """The showcase page loads the real stylesheet and renders its sections."""
    response = await client.get("/design-system")
    body = response.text

    assert "Design System" in body
    assert '/static/css/style.css' in body

    for section_id in (
        'id="colour"',
        'id="typography"',
        'id="buttons"',
        'id="forms"',
        'id="cards"',
        'id="modals"',
        'id="alerts"',
        'id="toasts"',
        'id="empty"',
        'id="badges"',
        'id="icons"',
        'id="voice"',
    ):
        assert section_id in body, f"missing section: {section_id}"

    assert "/static/js/toast.js" in body, "showcase must load toast.js"
    assert "WineBox.toast" in body, "showcase should demo the toast API"


@pytest.mark.asyncio
async def test_toast_js_is_served(client: AsyncClient) -> None:
    """toast.js is served as a JS file with the public API exposed."""
    response = await client.get("/static/js/toast.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]

    body = response.text
    for symbol in (
        "window.WineBox",
        "WineBox.toast",
        "function escapeHtml",
        "toast-container",
    ):
        assert symbol in body, f"toast.js missing: {symbol}"
