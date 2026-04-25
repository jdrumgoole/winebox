"""E2E visual capture of the design-system showcase in each theme.

Captures full-page screenshots of /design-system in both light and dark mode
so changes can be eyeballed against a baseline. The test passes whenever the
page renders without error and a non-empty PNG is produced — it is not a
strict pixel-diff check, just an artifact-generating smoke test.

Requirements:
    uv run python -m invoke start-background

Run with:
    uv run python -m pytest -m e2e tests/test_design_system_visual.py -v

Artifacts land in:
    artifacts/design-system-visual/
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page

from .playwright_utils import (
    BASE_URL,
    PROJECT_DIR,
    e2e_preflight,  # noqa: F401 — imported autouse fixture
)


ARTIFACTS = PROJECT_DIR / "artifacts" / "design-system-visual"


@pytest.mark.e2e
def test_design_system_theme_toggle_button_works(page: Page) -> None:
    """Click the showcase theme toggle and verify data-theme actually flips.

    Regression guard for CSP-blocked inline scripts: the visual tests below
    set localStorage via add_init_script, which bypasses the button. So if
    the toggle's wiring is blocked by CSP, those tests still pass while the
    user-facing button does nothing.
    """
    page.goto(f"{BASE_URL}/design-system", wait_until="networkidle")
    html = page.locator("html")

    assert html.get_attribute("data-theme") in (None, ""), (
        "expected no data-theme initially (auto), "
        f"got {html.get_attribute('data-theme')!r}"
    )

    btn = page.locator("#ds-theme-toggle")
    btn.wait_for(state="visible", timeout=3000)

    btn.click()
    page.wait_for_function(
        "document.documentElement.getAttribute('data-theme') === 'dark'",
        timeout=2000,
    )

    btn.click()
    page.wait_for_function(
        "document.documentElement.getAttribute('data-theme') === 'light'",
        timeout=2000,
    )

    btn.click()
    page.wait_for_function(
        "document.documentElement.getAttribute('data-theme') === null",
        timeout=2000,
    )


@pytest.mark.e2e
def test_design_system_no_csp_violations(page: Page) -> None:
    """Loading /design-system must produce zero CSP violations.

    Catches new inline <script> blocks or onclick= attributes that would
    be silently blocked by the project CSP.
    """
    violations: list[str] = []

    def on_msg(msg) -> None:  # type: ignore[no-untyped-def]
        text = msg.text or ""
        if msg.type == "error" and "Content Security Policy" in text:
            violations.append(text)

    page.on("console", on_msg)
    page.goto(f"{BASE_URL}/design-system", wait_until="networkidle")
    page.locator("[data-toast]").first.click()
    page.wait_for_timeout(200)

    assert not violations, "CSP violations on /design-system: " + " | ".join(violations)


@pytest.mark.e2e
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_design_system_full_page(page: Page, theme: str) -> None:
    """Render /design-system in `theme` and write a full-page PNG artifact."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    # Inject the theme preference into localStorage before the page's own
    # pre-paint script runs. The page reads `wb-theme` and applies data-theme
    # to <html> before first paint, so the screenshot captures the right theme.
    page.add_init_script(
        f"try {{ localStorage.setItem('wb-theme', '{theme}'); }} catch (e) {{}}"
    )

    page.goto(f"{BASE_URL}/design-system", wait_until="networkidle")

    # Confirm the theme actually took effect.
    page.locator(f"html[data-theme='{theme}']").wait_for(timeout=3000)

    out_path = ARTIFACTS / f"design-system-{theme}.png"
    page.screenshot(path=str(out_path), full_page=True)

    assert out_path.exists(), f"screenshot was not written to {out_path}"
    assert out_path.stat().st_size > 5_000, (
        f"screenshot at {out_path} is suspiciously small "
        f"({out_path.stat().st_size} bytes) — page may not have rendered"
    )


@pytest.mark.e2e
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(
    "section",
    [
        "colour",
        "typography",
        "buttons",
        "forms",
        "cards",
        "alerts",
        "empty",
        "badges",
        "icons",
    ],
)
def test_design_system_section(page: Page, theme: str, section: str) -> None:
    """Render a single showcase section and write a clipped PNG artifact."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    page.add_init_script(
        f"try {{ localStorage.setItem('wb-theme', '{theme}'); }} catch (e) {{}}"
    )
    page.goto(f"{BASE_URL}/design-system#{section}", wait_until="networkidle")
    page.locator(f"html[data-theme='{theme}']").wait_for(timeout=3000)

    locator = page.locator(f"section#{section}")
    locator.wait_for(state="visible", timeout=3000)

    out_path = ARTIFACTS / f"section-{section}-{theme}.png"
    locator.screenshot(path=str(out_path))

    assert out_path.exists(), f"screenshot was not written to {out_path}"
    assert out_path.stat().st_size > 1_000, (
        f"section screenshot at {out_path} is suspiciously small"
    )
