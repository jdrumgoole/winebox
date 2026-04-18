"""Manual test: check in a wine that triggers X-Wines enrichment and screenshot the detail modal.

This script:
1. Uses an existing registered/verified user, or registers+verifies a new one
2. Checks in a wine via API using a name that matches X-Wines ("Pinot Noir")
3. Opens the detail modal via Playwright
4. Takes a screenshot to verify X-Wines badges appear on enriched fields
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

RAND_SUFFIX = "".join(random.choices(string.ascii_lowercase, k=6))
TEST_EMAIL = f"enrichtest_{RAND_SUFFIX}@example.com"
TEST_PASSWORD = "TestPassword123!"


async def get_auth_token() -> str:
    """Register a user, verify via DB, and get an auth token."""
    mongodb_url = os.environ.get("WINEBOX_MONGODB_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("WINEBOX_DATABASE", "winebox-oat")

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Register
        reg_resp = await client.post(
            "/api/auth/register",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        print(f"Registration response: {reg_resp.status_code}")

        # Verify user directly in MongoDB
        mongo_client = AsyncMongoClient(mongodb_url)
        db = mongo_client[db_name]
        await db.users.update_one(
            {"email": TEST_EMAIL},
            {"$set": {"is_verified": True}},
        )
        mongo_client.close()

        # Login to get token
        login_resp = await client.post(
            "/api/auth/token",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if login_resp.status_code != 200:
            raise RuntimeError(f"Failed to get auth token: {login_resp.text}")

        return login_resp.json()["access_token"]


async def checkin_wine_via_api(token: str) -> dict:
    """Check in a wine via API with a name that matches X-Wines."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        with open(LABEL_PATH, "rb") as f:
            response = await client.post(
                "/api/wines/record",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "name": "Pinot Noir",
                    "quantity": "2",
                },
                files={"front_label": ("label.jpg", f, "image/jpeg")},
            )
        print(f"Check-in response: {response.status_code}")
        data = response.json()
        print(f"  Wine name: {data.get('name')}")
        print(f"  Winery: {data.get('winery')}")
        print(f"  Region: {data.get('region')}")
        print(f"  Country: {data.get('country')}")
        print(f"  Grape: {data.get('grape_variety')}")
        print(f"  Alcohol: {data.get('alcohol_percentage')}")
        print(f"  xwines_id: {data.get('xwines_id')}")
        print(f"  enriched_fields: {data.get('enriched_fields')}")
        return data


async def main() -> None:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Get auth token
    token = await get_auth_token()
    print(f"Got auth token: {token[:20]}...\n")

    # Check in wine via API (ensures matching name for enrichment)
    wine_data = await checkin_wine_via_api(token)
    wine_id = wine_data["id"]
    print(f"\nWine ID: {wine_id}")

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

        # Navigate to Cellar
        print("\nNavigating to Cellar...")
        cellar_link = page.locator(".nav-link:has-text('Cellar')")
        await cellar_link.first.click()
        await page.wait_for_timeout(3000)

        # Click on the wine card
        wine_card = page.locator(".wine-card")
        card_count = await wine_card.count()
        print(f"Found {card_count} wine cards")

        if card_count > 0:
            await wine_card.first.click()
            await page.wait_for_timeout(2000)

            # Screenshot detail modal
            detail_screenshot = os.path.join(SCREENSHOT_DIR, "checkin_enrichment_detail_modal.png")
            await page.screenshot(path=detail_screenshot, full_page=False)
            print(f"Detail modal screenshot: {detail_screenshot}")

            # Check for enriched fields (green-coloured values)
            enriched = page.locator(".enriched")
            enriched_count = await enriched.count()
            print(f"\nEnriched fields found: {enriched_count}")
            for i in range(enriched_count):
                el_text = await enriched.nth(i).inner_text()
                print(f"  Enriched {i+1}: {el_text.strip()}")

            if enriched_count == 0:
                print("\nNo enriched fields found - checking if enriched_fields exist on the wine...")
                # Get wine from API to debug
                async with httpx.AsyncClient(base_url=BASE_URL) as client:
                    resp = await client.get(
                        f"/api/wines/{wine_id}",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    detail = resp.json()
                    print(f"  API enriched_fields: {detail.get('enriched_fields')}")
                    print(f"  API xwines_id: {detail.get('xwines_id')}")
        else:
            print("No wine cards found!")

        await browser.close()
        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
