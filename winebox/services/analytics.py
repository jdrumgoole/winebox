"""PostHog analytics service for WineBox.

Provides server-side event tracking for user actions.
Uses PostHog Cloud EU (https://eu.posthog.com) for GDPR compliance.
"""

import logging
from typing import Any

from winebox.config import settings

logger = logging.getLogger(__name__)


class PostHogService:
    """PostHog analytics service.

    Handles server-side event tracking. All methods are no-ops
    if PostHog is not configured or disabled.
    """

    def __init__(self) -> None:
        """Initialize the PostHog service."""
        self._client: Any = None
        self._initialized = False

    def _ensure_initialized(self) -> bool:
        """Lazily initialize the PostHog client.

        Returns:
            True if client is available and ready.
        """
        if self._initialized:
            return self._client is not None

        self._initialized = True

        if not self.is_available():
            logger.debug("PostHog analytics disabled or not configured")
            return False

        try:
            import posthog

            posthog.project_api_key = settings.posthog_api_key
            posthog.host = settings.posthog_host
            posthog.debug = settings.posthog_debug

            # Disable automatic batch sending for serverless - we'll flush manually
            posthog.sync_mode = False

            self._client = posthog
            logger.info(
                "PostHog analytics initialized (host=%s, debug=%s)",
                settings.posthog_host,
                settings.posthog_debug,
            )
            return True
        except ImportError:
            logger.warning("PostHog package not installed")
            return False
        except Exception as e:
            logger.error("Failed to initialize PostHog: %s", e)
            return False

    def is_available(self) -> bool:
        """Check if PostHog analytics is configured and enabled.

        Returns:
            True if PostHog is enabled and API key is set.
        """
        return settings.posthog_enabled and bool(settings.posthog_api_key)

    def capture(
        self,
        distinct_id: str,
        event: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Capture an analytics event.

        Args:
            distinct_id: Unique identifier for the user (typically user ID).
            event: Event name (e.g., "user_login", "wine_checkin").
            properties: Optional dictionary of event properties.
        """
        if not self._ensure_initialized():
            return

        try:
            self._client.capture(
                distinct_id=distinct_id,
                event=event,
                properties=properties or {},
            )
            if settings.posthog_debug:
                logger.debug(
                    "PostHog event captured: %s (user=%s, props=%s)",
                    event,
                    distinct_id,
                    properties,
                )
        except Exception as e:
            logger.error("Failed to capture PostHog event: %s", e)

    def identify(
        self,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Identify a user with optional properties.

        Args:
            distinct_id: Unique identifier for the user.
            properties: Optional user properties (e.g., email, plan).
        """
        if not self._ensure_initialized():
            return

        try:
            self._client.identify(
                distinct_id=distinct_id,
                properties=properties or {},
            )
            if settings.posthog_debug:
                logger.debug(
                    "PostHog user identified: %s (props=%s)",
                    distinct_id,
                    properties,
                )
        except Exception as e:
            logger.error("Failed to identify PostHog user: %s", e)

    def shutdown(self) -> None:
        """Flush pending events and shutdown the client.

        Should be called during application shutdown to ensure
        all events are sent before the process exits.
        """
        if not self._initialized or self._client is None:
            return

        try:
            self._client.flush()
            self._client.shutdown()
            logger.info("PostHog client shutdown complete")
        except Exception as e:
            logger.error("Error during PostHog shutdown: %s", e)


# Global service instance
posthog_service = PostHogService()
