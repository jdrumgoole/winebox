"""Test that URL hashes align with tab names and favicon loads."""

import asyncio
import os
import random
import string

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from playwright.async_api import async_playwright

BASE_URL = os.environ.get("WINEBOX_URL", "http://localhost:8000")
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")


async def create_verified_user(email: str, password: str) -> str:
    """Register, verify, and get token for a user."""
    mongodb_url = os.environ.get("WINEBOX_MONGODB_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("WINEBOX_DATABASE_MONGODB_DATABASE", "winebox")

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        await client.post("/api/auth/register", json={"email": email, "password": password})

    mongo = AsyncIOMotorClient(mongodb_url)
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
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    email = f"hashtest_{suffix}@example.com"
    token = await create_verified_user(email, password)

    # Add a wine so we're not a first-time user
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        label_path = os.path.join(os.path.dirname(__file__), "..", "tests", "data", "wine_labels", "Jo_Pithon_Clos_des_Bois_SGN_1994_label.jpg")
        with open(label_path, "rb") as f:
            await client.post(
                "/api/wines/checkin",
                headers={"Authorization": f"Bearer {token}"},
                data={"name": "Hash Test Wine", "quantity": "1"},
                files={"front_label": ("label.jpg", f, "image/jpeg")},
            )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1200})
        page = await context.new_page()

        # Set auth token
        await page.goto(BASE_URL)
        await page.wait_for_load_state("networkidle")
        await page.evaluate(f"localStorage.setItem('winebox_token', '{token}')")
        await page.reload()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)

        # Test 1: Initial load should go to dashboard with #dashboard hash
        url = page.url
        active_nav = await page.locator(".nav-link.active").inner_text()
        print(f"1. Initial load:")
        print(f"   URL: {url}")
        print(f"   Active tab: {active_nav}")
        assert "#dashboard" in url, f"Expected #dashboard in URL, got {url}"

        # Test 2: Click on each nav tab and verify hash updates
        tabs_to_test = ["Import", "Check In", "Cellar", "History", "Search", "X-Wines"]
        expected_hashes = ["import", "checkin", "cellar", "history", "search", "xwines"]

        for tab_name, expected_hash in zip(tabs_to_test, expected_hashes):
            nav_link = page.locator(f".nav-link:has-text('{tab_name}')")
            await nav_link.first.click()
            await page.wait_for_timeout(500)

            url = page.url
            active_nav = await page.locator(".nav-link.active").inner_text()
            has_hash = f"#{expected_hash}" in url
            print(f"   Click '{tab_name}': URL has #{expected_hash} = {has_hash}, active = {active_nav}")
            assert has_hash, f"Expected #{expected_hash} in URL, got {url}"

        # Test 3: Direct URL navigation - load with #cellar hash
        print(f"\n2. Direct URL navigation:")
        await page.goto(f"{BASE_URL}/#cellar")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)

        active_nav = await page.locator(".nav-link.active").inner_text()
        active_page = await page.locator(".page.active").get_attribute("id")
        print(f"   Navigate to #cellar: active tab = {active_nav}, page = {active_page}")
        assert active_nav == "Cellar", f"Expected Cellar tab active, got {active_nav}"

        # Test 4: Direct URL navigation to #import
        await page.goto(f"{BASE_URL}/#import")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)

        active_nav = await page.locator(".nav-link.active").inner_text()
        print(f"   Navigate to #import: active tab = {active_nav}")
        assert active_nav == "Import", f"Expected Import tab active, got {active_nav}"

        # Test 5: Check favicon loads
        print(f"\n3. Favicon:")
        favicon_resp = await page.request.get(f"{BASE_URL}/favicon.ico")
        print(f"   /favicon.ico status: {favicon_resp.status}")
        assert favicon_resp.status == 200

        favicon_png_resp = await page.request.get(f"{BASE_URL}/static/logos/favicon.png")
        print(f"   /static/logos/favicon.png status: {favicon_png_resp.status}")
        assert favicon_png_resp.status == 200

        # Screenshot showing URL hash
        screenshot = os.path.join(SCREENSHOT_DIR, "url_hash_aligned.png")
        await page.screenshot(path=screenshot, full_page=False)
        print(f"\n   Screenshot: {screenshot}")

        await context.close()
        await browser.close()

    print("\nAll tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
