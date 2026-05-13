"""Post-deployment production login smoke test.

Verifies that a known test user can authenticate against the production
server immediately after deployment. This catches:
- Broken auth (bad secret key, parse_id issues, etc.)
- Email verification blocking login
- Database connectivity problems
- Safety guard misconfiguration

Run after every production deploy:
    uv run python -m pytest tests/test_production_login.py -v

Requires WINEBOX_PROD_TEST_USER and WINEBOX_PROD_TEST_PASSWORD in .env.
"""

import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

PROD_URL = "https://booze.winebox.app"
PROD_TEST_USER = os.environ.get("WINEBOX_PROD_TEST_USER")
PROD_TEST_PASSWORD = os.environ.get("WINEBOX_PROD_TEST_PASSWORD")


pytestmark = pytest.mark.skipif(
    not PROD_TEST_USER or not PROD_TEST_PASSWORD,
    reason="WINEBOX_PROD_TEST_USER and WINEBOX_PROD_TEST_PASSWORD must be set in .env",
)


def test_production_health():
    """Production server is reachable and healthy."""
    resp = requests.get(f"{PROD_URL}/health", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_production_login():
    """Test user can log in to production."""
    resp = requests.post(
        f"{PROD_URL}/api/auth/login",
        json={"email": PROD_TEST_USER, "password": PROD_TEST_PASSWORD},
        timeout=10,
    )
    assert resp.status_code == 200, (
        f"Login failed ({resp.status_code}): {resp.json().get('detail', resp.text)}"
    )
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_production_auth_me():
    """Authenticated API call works with the login token."""
    # Login first
    login_resp = requests.post(
        f"{PROD_URL}/api/auth/login",
        json={"email": PROD_TEST_USER, "password": PROD_TEST_PASSWORD},
        timeout=10,
    )
    token = login_resp.json()["access_token"]

    # Call /auth/me
    me_resp = requests.get(
        f"{PROD_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    assert me_resp.status_code == 200
    data = me_resp.json()
    assert data["email"] == PROD_TEST_USER
    assert data["is_active"] is True
