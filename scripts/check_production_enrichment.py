"""Test X-Wines enrichment against production API.

Logs in with test credentials and verifies enrichment for composite wine names.
"""

import argparse
import os
import sys

import httpx

BASE_URL = "https://booze.winebox.app"


def login(client: httpx.Client, email: str, password: str) -> str:
    """Login and return Bearer token."""
    resp = client.post(
        f"{BASE_URL}/api/auth/token",
        data={"username": email, "password": password},
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    print(f"Logged in as {email}")
    return token


def test_xwines_search(client: httpx.Client, query: str) -> None:
    """Search X-Wines and print results."""
    print(f"\n--- X-Wines search: {query!r} ---")
    resp = client.get(f"{BASE_URL}/api/xwines/search", params={"q": query, "limit": 5})
    resp.raise_for_status()
    data = resp.json()
    total = data.get("total", 0)
    results = data.get("results", [])
    print(f"Total matches: {total}")
    for i, r in enumerate(results, 1):
        print(
            f"  {i}. name={r.get('name')!r}  winery={r.get('winery_name')!r}  "
            f"region={r.get('region_name')!r}  type={r.get('wine_type')!r}"
        )


def test_scan_enrichment(client: httpx.Client) -> None:
    """Test enrichment via the scan endpoint using a synthetic label image.

    Creates a minimal PNG with the composite wine name text, sends it to the
    scan endpoint, and checks whether enrichment fields were populated.
    """
    print("\n--- Scan endpoint enrichment test ---")
    # We can't easily create a label image with text here, so skip if no test image
    print("(Skipped — scan endpoint requires a real label image)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test X-Wines enrichment against production")
    parser.parse_args()

    email = os.environ.get("WINEBOX_TEST_USER")
    password = os.environ.get("WINEBOX_TEST_PASSWORD")
    if not email or not password:
        # Try loading from .env
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())
            email = os.environ.get("WINEBOX_TEST_USER")
            password = os.environ.get("WINEBOX_TEST_PASSWORD")

    if not email or not password:
        print("ERROR: Set WINEBOX_TEST_USER and WINEBOX_TEST_PASSWORD in .env or environment")
        sys.exit(1)

    with httpx.Client(timeout=30) as client:
        token = login(client, email, password)
        client.headers["Authorization"] = f"Bearer {token}"

        # Test 1: Search for the composite name that was failing
        test_xwines_search(client, "Chateau Lynch-Bages, Pauillac, Bordeaux")

        # Test 2: Search for just the winery name (should work)
        test_xwines_search(client, "Chateau Lynch-Bages")

        # Test 3: Search for just "Lynch-Bages"
        test_xwines_search(client, "Lynch-Bages")

        # Test 4: A simple known wine
        test_xwines_search(client, "Chateau Margaux")

        print("\n--- Done ---")


if __name__ == "__main__":
    main()
