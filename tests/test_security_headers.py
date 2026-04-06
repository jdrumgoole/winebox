"""Tests for SecurityHeadersMiddleware in winebox/main.py."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestSecurityHeaders:
    """Tests for security headers on responses."""

    async def test_x_content_type_options(self, unauthenticated_client: AsyncClient):
        """X-Content-Type-Options: nosniff."""
        response = await unauthenticated_client.get("/health")
        assert response.headers.get("x-content-type-options") == "nosniff"

    async def test_x_frame_options(self, unauthenticated_client: AsyncClient):
        """X-Frame-Options: DENY."""
        response = await unauthenticated_client.get("/health")
        assert response.headers.get("x-frame-options") == "DENY"

    async def test_csp_header(self, unauthenticated_client: AsyncClient):
        """Content-Security-Policy present."""
        response = await unauthenticated_client.get("/health")
        csp = response.headers.get("content-security-policy")
        assert csp is not None
        assert "default-src" in csp
        assert "script-src" in csp

    async def test_referrer_policy(self, unauthenticated_client: AsyncClient):
        """Referrer-Policy header set."""
        response = await unauthenticated_client.get("/health")
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    async def test_permissions_policy(self, unauthenticated_client: AsyncClient):
        """Permissions-Policy header set."""
        response = await unauthenticated_client.get("/health")
        pp = response.headers.get("permissions-policy")
        assert pp is not None
        assert "camera=(self)" in pp
        assert "microphone=()" in pp
