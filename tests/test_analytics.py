"""Tests for PostHog analytics service."""

import pytest
from unittest.mock import MagicMock, patch

from winebox.services.analytics import PostHogService


class TestPostHogService:
    """Tests for the PostHog analytics service."""

    def test_is_available_returns_false_when_disabled(self) -> None:
        """Test is_available returns False when PostHog is disabled."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = False
            mock_settings.posthog_api_key = "test_key"

            service = PostHogService()
            assert service.is_available() is False

    def test_is_available_returns_false_when_no_api_key(self) -> None:
        """Test is_available returns False when no API key is set."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_api_key = None

            service = PostHogService()
            assert service.is_available() is False

    def test_is_available_returns_false_when_empty_api_key(self) -> None:
        """Test is_available returns False when API key is empty string."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_api_key = ""

            service = PostHogService()
            assert service.is_available() is False

    def test_is_available_returns_true_when_configured(self) -> None:
        """Test is_available returns True when properly configured."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_api_key = "phc_test_api_key"

            service = PostHogService()
            assert service.is_available() is True

    def test_capture_is_noop_when_not_available(self) -> None:
        """Test capture does nothing when PostHog is not available."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = False
            mock_settings.posthog_api_key = None

            service = PostHogService()
            # Should not raise any exception
            service.capture("test_user", "test_event", {"prop": "value"})

    def test_identify_is_noop_when_not_available(self) -> None:
        """Test identify does nothing when PostHog is not available."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = False
            mock_settings.posthog_api_key = None

            service = PostHogService()
            # Should not raise any exception
            service.identify("test_user", {"email": "test@example.com"})

    def test_shutdown_is_noop_when_not_initialized(self) -> None:
        """Test shutdown does nothing when service was never initialized."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = False
            mock_settings.posthog_api_key = None

            service = PostHogService()
            # Should not raise any exception
            service.shutdown()

    def test_capture_calls_posthog_when_available(self) -> None:
        """Test capture calls posthog.capture when available."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_api_key = "phc_test_api_key"
            mock_settings.posthog_host = "https://eu.posthog.com"
            mock_settings.posthog_debug = False

            with patch.dict("sys.modules", {"posthog": MagicMock()}):
                import sys

                mock_posthog = sys.modules["posthog"]

                service = PostHogService()
                service.capture("user_123", "test_event", {"key": "value"})

                mock_posthog.capture.assert_called_once_with(
                    distinct_id="user_123",
                    event="test_event",
                    properties={"key": "value"},
                )

    def test_identify_calls_posthog_when_available(self) -> None:
        """Test identify calls posthog.identify when available."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_api_key = "phc_test_api_key"
            mock_settings.posthog_host = "https://eu.posthog.com"
            mock_settings.posthog_debug = False

            with patch.dict("sys.modules", {"posthog": MagicMock()}):
                import sys

                mock_posthog = sys.modules["posthog"]

                service = PostHogService()
                service.identify("user_123", {"email": "user@example.com"})

                mock_posthog.identify.assert_called_once_with(
                    distinct_id="user_123",
                    properties={"email": "user@example.com"},
                )

    def test_shutdown_flushes_and_shuts_down_client(self) -> None:
        """Test shutdown flushes and shuts down the PostHog client."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_api_key = "phc_test_api_key"
            mock_settings.posthog_host = "https://eu.posthog.com"
            mock_settings.posthog_debug = False

            with patch.dict("sys.modules", {"posthog": MagicMock()}):
                import sys

                mock_posthog = sys.modules["posthog"]

                service = PostHogService()
                # Force initialization
                service._ensure_initialized()

                service.shutdown()

                mock_posthog.flush.assert_called_once()
                mock_posthog.shutdown.assert_called_once()

    def test_capture_with_none_properties(self) -> None:
        """Test capture works with None properties."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_api_key = "phc_test_api_key"
            mock_settings.posthog_host = "https://eu.posthog.com"
            mock_settings.posthog_debug = False

            with patch.dict("sys.modules", {"posthog": MagicMock()}):
                import sys

                mock_posthog = sys.modules["posthog"]

                service = PostHogService()
                service.capture("user_123", "test_event", None)

                mock_posthog.capture.assert_called_once_with(
                    distinct_id="user_123",
                    event="test_event",
                    properties={},
                )

    def test_identify_with_none_properties(self) -> None:
        """Test identify works with None properties."""
        with patch("winebox.services.analytics.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_api_key = "phc_test_api_key"
            mock_settings.posthog_host = "https://eu.posthog.com"
            mock_settings.posthog_debug = False

            with patch.dict("sys.modules", {"posthog": MagicMock()}):
                import sys

                mock_posthog = sys.modules["posthog"]

                service = PostHogService()
                service.identify("user_123", None)

                mock_posthog.identify.assert_called_once_with(
                    distinct_id="user_123",
                    properties={},
                )


class TestAnalyticsConfigEndpoint:
    """Tests for the /api/config/analytics endpoint."""

    @pytest.mark.asyncio
    async def test_analytics_config_endpoint_returns_disabled_when_not_configured(
        self,
    ) -> None:
        """Test the analytics config endpoint returns disabled state."""
        from httpx import ASGITransport, AsyncClient

        with patch("winebox.main.settings") as mock_settings:
            mock_settings.posthog_enabled = False
            mock_settings.posthog_host = "https://eu.posthog.com"
            mock_settings.posthog_api_key = None
            mock_settings.app_name = "WineBox"
            mock_settings.cors_origins = []
            mock_settings.enforce_https = False

            # Import app after patching
            from winebox.main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/config/analytics")
                assert response.status_code == 200
                data = response.json()
                assert data["enabled"] is False
                assert data["host"] == "https://eu.posthog.com"
                assert data["api_key"] == ""

    @pytest.mark.asyncio
    async def test_analytics_config_endpoint_returns_config_when_enabled(
        self,
    ) -> None:
        """Test the analytics config endpoint returns full config when enabled."""
        from httpx import ASGITransport, AsyncClient

        with patch("winebox.main.settings") as mock_settings:
            mock_settings.posthog_enabled = True
            mock_settings.posthog_host = "https://eu.posthog.com"
            mock_settings.posthog_api_key = "phc_test_key"
            mock_settings.app_name = "WineBox"
            mock_settings.cors_origins = []
            mock_settings.enforce_https = False

            from winebox.main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/config/analytics")
                assert response.status_code == 200
                data = response.json()
                assert data["enabled"] is True
                assert data["host"] == "https://eu.posthog.com"
                assert data["api_key"] == "phc_test_key"
