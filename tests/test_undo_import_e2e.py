"""E2E tests for undo import on the Import tab.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_undo_import_e2e.py -v --override-ini="addopts="
"""

from typing import Generator

import pytest
from playwright.sync_api import Page, expect

from .playwright_utils import (
    BASE_URL,
    create_cli_worker_user,
    login_via_ui,
    preflight_check,
)


@pytest.fixture(scope="session", autouse=True)
def _e2e_preflight() -> None:
    preflight_check()


@pytest.fixture(scope="session")
def worker_user(request: pytest.FixtureRequest) -> Generator[tuple[str, str], None, None]:
    email, password = create_cli_worker_user(request, email_prefix="e2e_undo", password="testpass123")
    yield email, password


@pytest.fixture(scope="function")
def authenticated_page(page: Page, worker_user: tuple[str, str]) -> Page:
    email, password = worker_user
    login_via_ui(page, email=email, password=password)
    return page


def _navigate_to_import_tab(page: Page) -> None:
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#page-cellar", state="visible", timeout=5000)
    page.click("[data-cellar-tab='import']")
    page.wait_for_selector("#cellar-panel-import", state="visible", timeout=5000)


@pytest.mark.e2e
class TestUndoImport:
    """E2E tests for the undo import feature on the Import tab."""

    def test_undo_button_hidden_when_no_imports(self, authenticated_page: Page) -> None:
        """Undo button is not visible when user has no imports."""
        page = authenticated_page

        # Clean up any existing data
        page.evaluate("""async () => {
            const token = localStorage.getItem('winebox_token');
            if (!token) return;
            const resp = await fetch('/api/import/batches', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            const batches = await resp.json();
            for (const b of batches) {
                if (b.status === 'completed') {
                    await fetch('/api/import/batches/' + b.id + '/wines', {
                        method: 'DELETE',
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                }
                await fetch('/api/import/batches/' + b.id, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + token }
                });
            }
        }""")

        _navigate_to_import_tab(page)
        page.wait_for_timeout(1000)  # Allow async load

        undo_actions = page.locator("#import-tab-actions")
        expect(undo_actions).not_to_be_visible()

    def test_undo_button_shown_after_import(self, authenticated_page: Page) -> None:
        """After importing wines via API, the undo button appears on Import tab."""
        page = authenticated_page

        # Create a completed import via API
        result = page.evaluate("""async () => {
            const token = localStorage.getItem('winebox_token');
            const csv = 'Name,Vintage\\nTest Undo Wine,2020\\n';
            const blob = new Blob([csv], { type: 'text/csv' });
            const form = new FormData();
            form.append('file', blob, 'undo_test.csv');

            const upload = await fetch('/api/import/upload', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token },
                body: form
            });
            const data = await upload.json();
            const batchId = data.batch_id;

            // Set mapping
            await fetch('/api/import/' + batchId + '/mapping', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ mapping: { 'Name': 'name', 'Vintage': 'vintage' } })
            });

            // Process
            const processResp = await fetch('/api/import/' + batchId + '/process', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    skip_non_wine: true,
                    default_quantity: 1,
                    skip_enrichment: true,
                    default_case_size: 0
                })
            });
            const processResult = await processResp.json();

            // Verify batch is completed
            const statusResp = await fetch('/api/import/batches/' + batchId, {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            const batch = await statusResp.json();
            return { batchId, status: batch.status, wines: processResult.wines_created };
        }""")

        assert result["status"] == "completed", f"Batch not completed: {result}"
        assert result["wines"] > 0, f"No wines created: {result}"

        _navigate_to_import_tab(page)
        page.wait_for_selector("#import-tab-actions", state="visible", timeout=30000)

        expect(page.locator("#import-tab-undo-btn")).to_be_visible()
        expect(page.locator("#import-tab-last-import")).to_contain_text("undo_test.csv")
