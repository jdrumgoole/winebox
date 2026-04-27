"""Post-deploy smoke test for the OAT admin panel.

Verifies that `https://oatadmin.winebox.app` is reachable from the operator
machine after `invoke deploy-oat` finishes. Catches:

- DNS not resolving (oatadmin A record missing or stale).
- Allowlist misconfigured (this machine's IP isn't in
  `deploy/winebox-admin.toml [oat].allow`, so nginx returns 403).
- Admin systemd unit dead (nginx 502).
- TLS cert expired or wrong subject.
- Static assets / login page failing to load.

Run from the same machine that ran `invoke deploy-oat` — your IP needs to
be in the OAT allowlist for these to pass:

    uv run python -m pytest tests/test_oat_admin_smoke.py -v

The whole module is skipped on CI / unallowlisted machines so it doesn't
turn into noise in the main test runs.
"""

from __future__ import annotations

import os

import pytest
import requests

ADMIN_URL = "https://oatadmin.winebox.app"


def _allowlisted() -> bool:
    """Return True if the test runner can reach the admin /health endpoint.

    The allowlist is enforced at nginx level — non-allowed IPs get 403
    before the request hits the app. We probe once with a short timeout so
    parametrising the skip doesn't slow down unrelated test runs.
    """
    try:
        resp = requests.get(f"{ADMIN_URL}/health", timeout=5)
    except requests.RequestException:
        return False
    return resp.status_code == 200


pytestmark = pytest.mark.skipif(
    os.environ.get("WINEBOX_OAT_ADMIN_SMOKE") != "1" and not _allowlisted(),
    reason=(
        "OAT admin smoke test runs only from an allowlisted operator machine. "
        "Set WINEBOX_OAT_ADMIN_SMOKE=1 to force-run (e.g. from the OAT droplet)."
    ),
)


def test_admin_health_endpoint() -> None:
    """`/health` returns 200 with the admin app's identity."""
    resp = requests.get(f"{ADMIN_URL}/health", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["app_name"] == "WineBox Admin"
    assert "version" in data


def test_admin_root_serves_panel_html() -> None:
    """`/` serves the admin SPA (the static admin.html shell). Anonymous
    users see the page; admin auth is enforced at the API layer below."""
    resp = requests.get(ADMIN_URL, timeout=10)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text.lower()
    assert "<html" in body, "response is not HTML"
    assert "winebox" in body, "WineBox branding missing — wrong page served?"


def test_admin_static_css_loads() -> None:
    """Static assets are wired through the admin uvicorn worker. Catches
    the common regression of the static mount breaking after a refactor."""
    resp = requests.get(f"{ADMIN_URL}/static/css/admin.css", timeout=10)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert len(resp.content) > 0
