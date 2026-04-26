"""Capture every major WineBox screen in light and dark mode for review.

Used as a one-shot audit tool (not a pytest test) so a human can scroll
through artifacts/dark-mode-audit/ and judge legibility issues.

Run after starting a local server pointing at winebox_oat:

    uv run python scripts/audit_dark_mode.py \
        --base-url http://localhost:8000 \
        --email darkmode-audit@test.example.com \
        --password DarkModeAudit123!

Each screen produces two PNGs (one per theme) named ``<screen>-<theme>.png``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, sync_playwright


def _wait(page: Page, ms: int = 400) -> None:
    page.wait_for_timeout(ms)


def login(page: Page, email: str, password: str) -> None:
    page.fill("#login-email", email)
    page.fill("#login-password", password)
    page.click("#login-form button[type='submit']")
    page.wait_for_selector("#user-info", state="visible", timeout=10_000)


def goto_cellar_dashboard(page: Page) -> None:
    page.click("a[data-page='cellar']")
    page.wait_for_selector("#cellar-panel-dashboard", state="visible", timeout=5_000)
    _wait(page)


def ensure_sample_data(page: Page) -> None:
    """Click 'Load sample wines' if the empty-state offers it."""
    goto_cellar_dashboard(page)
    btn = page.locator("#dashboard-demo-install-btn")
    if btn.is_visible():
        btn.click()
        # Demo install can take several seconds.
        page.wait_for_selector("#stat-total-bottles", state="visible", timeout=30_000)
        page.wait_for_function(
            "document.getElementById('stat-total-bottles').textContent.trim() !== '-'",
            timeout=30_000,
        )
        _wait(page, 1_000)


def click_cellar_tab(page: Page, tab: str) -> None:
    page.click(f"[data-cellar-tab='{tab}']")
    page.wait_for_selector(f"#cellar-panel-{tab}", state="visible", timeout=5_000)
    _wait(page)


def search_for_wine(page: Page) -> None:
    click_cellar_tab(page, "search")
    box = page.locator("#search-q")
    if box.is_visible():
        box.fill("red")
        page.keyboard.press("Enter")
        page.wait_for_timeout(2_000)


def click_first_wine_card(page: Page) -> None:
    cards = page.locator(".wine-card")
    if cards.count() > 0:
        cards.first.click()
        page.wait_for_selector("#wine-modal.active", state="visible", timeout=10_000)
        _wait(page)


# Each entry is (slug, navigator). The navigator runs against an already-
# logged-in page that has had sample data loaded.
SCREENS: list[tuple[str, Callable[[Page], None]]] = [
    ("cellar-dashboard", goto_cellar_dashboard),
    ("cellar-search", search_for_wine),
    ("cellar-import", lambda p: click_cellar_tab(p, "import")),
    ("cellar-export", lambda p: click_cellar_tab(p, "export")),
    ("cellar-history", lambda p: click_cellar_tab(p, "history")),
    ("met", lambda p: p.click("a[data-page='met']")),
    ("xwines", lambda p: p.click("a[data-page='xwines']")),
    ("settings", lambda p: p.click("a[data-page='settings']")),
    ("record-wine", lambda p: p.click("a[data-page='record-wine']")),
    ("wine-detail-modal", click_first_wine_card),
]


def capture(base_url: str, email: str, password: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        for theme in ("light", "dark"):
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            ctx.add_init_script(
                f"try {{ localStorage.setItem('wb-theme', '{theme}'); }} catch (e) {{}}"
            )
            page = ctx.new_page()

            page.goto(base_url, wait_until="networkidle")

            # Unauth screens before login
            page.screenshot(
                path=str(output / f"login-{theme}.png"), full_page=True
            )
            page.click("#show-register")
            _wait(page)
            page.screenshot(
                path=str(output / f"register-{theme}.png"), full_page=True
            )
            page.click("#show-login-from-register")
            _wait(page)

            login(page, email, password)
            ensure_sample_data(page)

            for slug, navigator in SCREENS:
                try:
                    if slug == "wine-detail-modal":
                        # Need to be on a page with wine cards first.
                        click_cellar_tab(page, "search")
                        page.locator("#search-q").fill("red")
                        page.keyboard.press("Enter")
                        page.wait_for_selector(
                            ".wine-card", state="visible", timeout=10_000
                        )
                        navigator(page)
                    else:
                        navigator(page)
                    _wait(page, 600)
                    page.screenshot(
                        path=str(output / f"{slug}-{theme}.png"), full_page=True
                    )
                except Exception as exc:
                    print(f"[{theme}] {slug}: capture failed — {exc}")
                # Close modal if it's open before next nav.
                if page.locator("#wine-modal.active").count() > 0:
                    page.evaluate(
                        "document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))"
                    )

            browser.close()
            print(f"[{theme}] done")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "artifacts"
        / "dark-mode-audit",
    )
    args = parser.parse_args()
    capture(args.base_url, args.email, args.password, args.output)
    print(f"Audit complete. Screenshots in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
