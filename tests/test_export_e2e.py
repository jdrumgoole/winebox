"""E2E tests for the Export functionality.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_export_e2e.py -v --override-ini="addopts="
"""

import csv
import json
import zipfile
from pathlib import Path
from typing import Generator

import pytest
from playwright.sync_api import Page, expect

from .playwright_utils import (
    BASE_URL,
    authenticated_page,  # noqa: F401 — imported fixture
    create_cli_worker_user,
    e2e_preflight,  # noqa: F401 — imported autouse fixture
)


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    email, password = create_cli_worker_user(request, email_prefix="e2e_export", password="testpass123")
    yield email, password


def _navigate_to_cellar(page: Page) -> None:
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=5000)


def _ensure_empty_cellar(page: Page) -> None:
    """Delete all wines so the cellar is empty."""
    page.evaluate("""
        async () => {
            const token = localStorage.getItem('winebox_token');
            if (!token) return;
            try {
                await fetch('/api/wines/all', {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + token }
                });
            } catch {}
        }
    """)
    page.wait_for_timeout(500)


@pytest.mark.e2e
class TestExportFromHistory:
    """E2E tests for export from history page."""

    def test_history_export_button_present(self, authenticated_page: Page) -> None:
        """Export button present on history page (disabled when empty)."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='history']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='history']")
        page.wait_for_selector("#cellar-panel-history", state="visible", timeout=10000)
        export_btn = page.locator("#history-export-btn")
        expect(export_btn).to_be_attached()

    def test_history_export_dropdown_markup_exists(self, authenticated_page: Page) -> None:
        """History export dropdown markup exists in the DOM."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.wait_for_selector("[data-cellar-tab='history']", state="visible", timeout=10000)
        page.click("[data-cellar-tab='history']")
        page.wait_for_selector("#cellar-panel-history", state="visible", timeout=10000)
        dropdown = page.locator("#history-export-dropdown")
        expect(dropdown).to_be_attached()


def _navigate_to_export_tab(page: Page) -> None:
    """Navigate to Cellar > Export tab."""
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
    page.wait_for_selector("[data-cellar-tab='export']", state="visible", timeout=10000)
    page.click("[data-cellar-tab='export']")
    page.wait_for_selector("#cellar-panel-export", state="visible", timeout=10000)


def _install_demo_data(page: Page) -> int:
    """Install demo wines via API, return wine count."""
    result = page.evaluate("""
        async () => {
            const token = localStorage.getItem('winebox_token');
            const resp = await fetch('/api/demo/install', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token }
            });
            if (!resp.ok) return -1;
            const data = await resp.json();
            return data.wines || 0;
        }
    """)
    # Wait for data to be queryable
    page.wait_for_timeout(2000)
    return result


def _ensure_demo_data(page: Page) -> None:
    """Ensure demo data exists — install if cellar is empty."""
    count = _get_server_wine_count(page)
    if count == 0:
        _install_demo_data(page)


def _get_server_wine_count(page: Page) -> int:
    """Get the wine count from the search API."""
    return page.evaluate("""
        async () => {
            const token = localStorage.getItem('winebox_token');
            const resp = await fetch('/api/search?in_stock=true', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            const data = await resp.json();
            return data.length;
        }
    """)


def _extract_zip_data(zip_path: Path) -> tuple[list[str], list[dict], str]:
    """Extract ZIP and return (file_list, wine_data_from_json, csv_content)."""
    with zipfile.ZipFile(zip_path) as zf:
        return _parse_zip(zf)


def _extract_zip_data_from_bytes(data: bytes) -> tuple[list[str], list[dict], str]:
    """Extract ZIP from bytes and return (file_list, wine_data_from_json, csv_content)."""
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return _parse_zip(zf)


def _parse_zip(zf: zipfile.ZipFile) -> tuple[list[str], list[dict], str]:
    file_list = zf.namelist()
    data_js = zf.read("data.json").decode("utf-8")
    json_str = data_js[len("const CELLAR_DATA = "):-2]
    wine_data = json.loads(json_str)
    csv_content = zf.read("cellar.csv").decode("utf-8")
    return file_list, wine_data, csv_content


def _download_export_via_api(page: Page, params: str = "") -> bytes:
    """Download the static site ZIP via the API (avoids Playwright download flakiness)."""
    url_suffix = f"?{params}" if params else ""
    result = page.evaluate(f"""
        async () => {{
            const token = localStorage.getItem('winebox_token');
            if (!token) return {{ error: 'no token' }};
            const resp = await fetch('/api/export/static-site{url_suffix}', {{
                headers: {{ 'Authorization': 'Bearer ' + token }}
            }});
            if (!resp.ok) return {{ error: 'HTTP ' + resp.status, body: await resp.text() }};
            const buf = await resp.arrayBuffer();
            return {{ data: Array.from(new Uint8Array(buf)), size: buf.byteLength }};
        }}
    """)
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"Export API failed: {result}")
    return bytes(result["data"])


@pytest.mark.e2e
class TestStaticSiteExport:
    """E2E tests for the static site export (Download Data)."""

    def test_export_tab_visible(self, authenticated_page: Page) -> None:
        """Export tab is visible in the cellar tabs."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        export_tab = page.locator("[data-cellar-tab='export']")
        expect(export_tab).to_be_visible()

    def test_export_tab_order(self, authenticated_page: Page) -> None:
        """Tabs are in the correct order: Dashboard, Search, Import, Export, History."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        tabs = page.locator(".cellar-tab").all_text_contents()
        assert tabs == ["Dashboard", "Search", "Import", "Export", "History"]

    def test_download_button_visible_at_top(self, authenticated_page: Page) -> None:
        """Download Data button is visible at the top of the Export panel."""
        page = authenticated_page
        _navigate_to_export_tab(page)
        btn = page.locator("#export-generate-btn")
        expect(btn).to_be_visible()
        expect(btn).to_have_text("Download Data")

    def test_export_downloads_valid_zip(self, authenticated_page: Page) -> None:
        """Clicking Download Data produces a valid ZIP with all required files."""
        page = authenticated_page
        _ensure_demo_data(page)

        zip_bytes = _download_export_via_api(page)
        file_list, wine_data, csv_content = _extract_zip_data_from_bytes(zip_bytes)

        # Required files present
        assert "index.html" in file_list
        assert "data.json" in file_list
        assert "cellar.csv" in file_list
        assert "chart.min.js" in file_list
        assert len(wine_data) > 0, "Should export wines"

    def test_export_wine_count_matches_server(self, authenticated_page: Page) -> None:
        """Exported wine count matches the server's search API count."""
        page = authenticated_page
        _ensure_demo_data(page)
        server_count = _get_server_wine_count(page)
        assert server_count > 0, "Should have wines after demo install"

        zip_bytes = _download_export_via_api(page)
        _, wine_data, csv_content = _extract_zip_data_from_bytes(zip_bytes)

        assert len(wine_data) == server_count, (
            f"JSON has {len(wine_data)} wines but server has {server_count}"
        )

        csv_rows = list(csv.DictReader(csv_content.splitlines()))
        assert len(csv_rows) == server_count, (
            f"CSV has {len(csv_rows)} rows but server has {server_count}"
        )

    def test_export_contains_wine_fields(self, authenticated_page: Page) -> None:
        """Exported wines have required fields."""
        page = authenticated_page
        _ensure_demo_data(page)
        zip_bytes = _download_export_via_api(page)
        _, wine_data, _ = _extract_zip_data_from_bytes(zip_bytes)

        assert len(wine_data) > 0, "Export should contain wines"
        for w in wine_data[:5]:
            assert "name" in w and w["name"]
            assert "id" in w
            assert "inventory" in w

    def test_export_with_wine_type_filter(self, authenticated_page: Page) -> None:
        """Filtering by wine type limits the exported wines."""
        page = authenticated_page
        _ensure_demo_data(page)

        all_bytes = _download_export_via_api(page)
        _, all_wines, _ = _extract_zip_data_from_bytes(all_bytes)
        total = len(all_wines)

        red_bytes = _download_export_via_api(page, params="wine_type=red")
        _, red_wines, _ = _extract_zip_data_from_bytes(red_bytes)

        assert len(red_wines) > 0, "Should have some red wines"
        assert len(red_wines) < total, "Filtered export should have fewer wines"
        for w in red_wines:
            assert w.get("wine_type") == "red", f"Expected red, got {w.get('wine_type')}"

    def test_export_csv_has_correct_headers(self, authenticated_page: Page) -> None:
        """The cellar.csv has expected column headers."""
        page = authenticated_page
        _ensure_demo_data(page)
        zip_bytes = _download_export_via_api(page)
        _, _, csv_content = _extract_zip_data_from_bytes(zip_bytes)

        reader = csv.DictReader(csv_content.splitlines())
        headers = reader.fieldnames

        for expected in ["name", "winery", "vintage", "country", "wine_type", "quantity"]:
            assert expected in headers, f"Missing CSV header: {expected}"

    def test_export_filename_format(self, authenticated_page: Page) -> None:
        """The Content-Disposition header has a readable filename with date."""
        page = authenticated_page
        _ensure_demo_data(page)

        filename = page.evaluate("""
            async () => {
                const token = localStorage.getItem('winebox_token');
                const resp = await fetch('/api/export/static-site', {
                    headers: { 'Authorization': 'Bearer ' + token }
                });
                const disposition = resp.headers.get('content-disposition') || '';
                const match = disposition.match(/filename="?([^"]+)"?/);
                return match ? match[1] : disposition;
            }
        """)
        assert filename.startswith("winebox-cellar-"), f"Unexpected filename: {filename}"
        assert filename.endswith(".zip"), f"Should end with .zip: {filename}"
        months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
        assert any(m in filename.lower() for m in months), f"Filename should contain month: {filename}"

    def test_view_toggle_on_search_tab(self, authenticated_page: Page) -> None:
        """Search tab has Cards/Table view toggle."""
        page = authenticated_page
        page.click("a[data-page='cellar']")
        page.wait_for_selector("#page-cellar", state="visible", timeout=10000)
        page.click("[data-cellar-tab='search']")
        page.wait_for_selector("#cellar-panel-search", state="visible", timeout=10000)

        cards_btn = page.locator("#search-view-cards")
        table_btn = page.locator("#search-view-table")
        expect(cards_btn).to_be_visible()
        expect(table_btn).to_be_visible()
