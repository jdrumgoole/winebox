"""Manual test: verify Import tab order and first-time user behavior.

Screenshots:
1. First-time user (no wines) -> should land on Import page
2. Returning user (has wines) -> should land on Dashboard
3. Nav bar showing Import tab position (after Dashboard)
"""

import asyncio
import os
import random
import string

import httpx
from pymongo import AsyncMongoClient
from playwright.async_api import async_playwright

BASE_URL = os.environ.get("WINEBOX_URL", "http://localhost:8000")
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
LABEL_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "tests",
    "data",
    "wine_labels",
    "Jo_Pithon_Clos_des_Bois_SGN_1994_label.jpg",
)


async def create_verified_user(email: str, password: str) -> str:
    """Register, verify, and get token for a user."""
    mongodb_url = os.environ.get("WINEBOX_MONGODB_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("WINEBOX_DATABASE", "winebox")

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        await client.post("/api/auth/register", json={"email": email, "password": password})

    mongo = AsyncMongoClient(mongodb_url)
    await mongo[db_name].users.update_one({"email": email}, {"$set": {"is_verified": True}})
    mongo.close()

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.post(
            "/api/auth/token",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return resp.json()["access_token"]


async def main() -> None:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    password = "TestPassword123!"

    # --- Scenario 1: First-time user (empty cellar) ---
    suffix1 = "".join(random.choices(string.ascii_lowercase, k=6))
    email1 = f"firsttime_{suffix1}@example.com"
    token1 = await create_verified_user(email1, password)
    print(f"First-time user: {email1}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # First-time user
        ctx1 = await browser.new_context(viewport={"width": 1920, "height": 1200})
        page1 = await ctx1.new_page()
        await page1.goto(BASE_URL)
        await page1.wait_for_load_state("networkidle")
        await page1.evaluate(f"localStorage.setItem('winebox_token', '{token1}')")
        await page1.reload()
        await page1.wait_for_load_state("networkidle")
        await page1.wait_for_timeout(3000)

        # Check which page is active
        active_nav = await page1.locator(".nav-link.active").inner_text()
        active_page = await page1.locator(".page.active").get_attribute("id")
        print(f"  Active nav: {active_nav}")
        print(f"  Active page: {active_page}")

        screenshot1 = os.path.join(SCREENSHOT_DIR, "import_first_time_user.png")
        await page1.screenshot(path=screenshot1, full_page=True)
        print(f"  Screenshot: {screenshot1}")

        # Check nav order
        nav_links = page1.locator("#main-nav .nav-link")
        nav_count = await nav_links.count()
        nav_texts = []
        for i in range(nav_count):
            nav_texts.append(await nav_links.nth(i).inner_text())
        print(f"  Nav order: {' | '.join(nav_texts)}")

        await ctx1.close()

        # --- Scenario 2: Returning user (has wines) ---
        suffix2 = "".join(random.choices(string.ascii_lowercase, k=6))
        email2 = f"returning_{suffix2}@example.com"
        token2 = await create_verified_user(email2, password)
        print(f"\nReturning user: {email2}")

        # Add a wine via API
        async with httpx.AsyncClient(base_url=BASE_URL) as client:
            with open(LABEL_PATH, "rb") as f:
                await client.post(
                    "/api/wines/checkin",
                    headers={"Authorization": f"Bearer {token2}"},
                    data={"name": "Test Wine", "quantity": "1"},
                    files={"front_label": ("label.jpg", f, "image/jpeg")},
                )
        print("  Added wine to cellar")

        ctx2 = await browser.new_context(viewport={"width": 1920, "height": 1200})
        page2 = await ctx2.new_page()
        await page2.goto(BASE_URL)
        await page2.wait_for_load_state("networkidle")
        await page2.evaluate(f"localStorage.setItem('winebox_token', '{token2}')")
        await page2.reload()
        await page2.wait_for_load_state("networkidle")
        await page2.wait_for_timeout(3000)

        active_nav2 = await page2.locator(".nav-link.active").inner_text()
        active_page2 = await page2.locator(".page.active").get_attribute("id")
        print(f"  Active nav: {active_nav2}")
        print(f"  Active page: {active_page2}")

        screenshot2 = os.path.join(SCREENSHOT_DIR, "import_returning_user.png")
        await page2.screenshot(path=screenshot2, full_page=True)
        print(f"  Screenshot: {screenshot2}")

        await ctx2.close()
        await browser.close()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
