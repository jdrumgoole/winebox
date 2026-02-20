"""Claude Vision service for wine label analysis."""

import base64
import hashlib
import json
import logging
import os
import time
from typing import Any

from winebox.config import settings

logger = logging.getLogger(__name__)

# Client cache with TTL (5 minutes)
_client_cache: dict[str, tuple[Any, float]] = {}
_CACHE_TTL = 300  # 5 minutes

WINE_ANALYSIS_PROMPT = """Analyze this wine label image and extract the following information.
Return ONLY a valid JSON object with these fields (use null for any field you cannot determine):

{
    "name": "The wine name/title",
    "winery": "The winery or producer name",
    "vintage": 2020,
    "grape_variety": "Primary grape if single varietal, or dominant grape if blend",
    "grape_varieties": [
        {"name": "Cabernet Sauvignon", "percentage": 70},
        {"name": "Merlot", "percentage": 30}
    ],
    "region": "The wine region (e.g., Napa Valley, Bordeaux)",
    "appellation": "Specific appellation/AOC/DOC if shown (e.g., Margaux, Pomerol)",
    "country": "The country of origin",
    "wine_type": "red, white, rosé, sparkling, fortified, or dessert",
    "classification": "Quality classification if shown (e.g., Grand Cru, DOCG, Reserve)",
    "alcohol_percentage": 13.5,
    "drink_window": "2025-2040",
    "producer_type": "estate, negociant, or cooperative",
    "raw_text": "All readable text from the label, preserving line breaks"
}

Important:
- vintage should be a number (year) or null
- alcohol_percentage should be a number or null
- grape_varieties is an array with name and percentage (percentage can be null if not shown)
- wine_type should be one of: red, white, rosé, sparkling, fortified, dessert (infer from grape, color, region if not explicit)
- classification: look for quality indicators like:
  - France: Grand Cru, Premier Cru, AOC, AOP, Cru Classé, Cru Bourgeois
  - Italy: DOCG, DOC, IGT, Riserva
  - Spain: Crianza, Reserva, Gran Reserva, DOCa, DO
  - Germany: Kabinett, Spätlese, Auslese, GG (Grosses Gewächs)
  - USA: Estate Bottled, Reserve
- appellation: extract the specific sub-region/appellation (more specific than region)
- drink_window: if suggested drinking years are shown (e.g., "Best 2025-2040")
- producer_type: "estate" if estate-bottled/grown, "negociant" if merchant bottler, "cooperative" if co-op
- Extract ALL visible text for raw_text, including small print
- If you see multiple wines or labels, focus on the main/primary one
- Be thorough - wine labels often have text in multiple locations"""


class ClaudeVisionService:
    """Service for analyzing wine labels using Claude's vision capabilities."""

    def __init__(self) -> None:
        """Initialize the Claude Vision service."""
        self._default_client = None

    def _get_system_api_key(self) -> str | None:
        """Get the system-wide API key from settings or environment."""
        return settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")

    def _get_client(self, user_api_key: str | None = None):
        """Get an Anthropic client, using user key if provided, else system key.

        Clients are cached with a TTL to avoid recreating them on every request.
        """
        try:
            import anthropic

            # Use user's API key if provided, otherwise use system key
            api_key = user_api_key or self._get_system_api_key()
            if not api_key:
                raise ValueError("No Anthropic API key configured")

            # If using system key, cache the client
            if not user_api_key:
                if self._default_client is None:
                    self._default_client = anthropic.Anthropic(api_key=api_key)
                return self._default_client

            # Cache user-specific clients with TTL
            # Hash the API key to use as cache key (don't store raw key in memory)
            cache_key = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            now = time.time()

            # Check cache
            if cache_key in _client_cache:
                client, cached_at = _client_cache[cache_key]
                if now - cached_at < _CACHE_TTL:
                    return client
                # Expired, remove from cache
                del _client_cache[cache_key]

            # Create new client and cache it
            client = anthropic.Anthropic(api_key=api_key)
            _client_cache[cache_key] = (client, now)

            # Clean up expired entries periodically (simple approach)
            if len(_client_cache) > 100:
                expired_keys = [
                    k for k, (_, t) in _client_cache.items() if now - t >= _CACHE_TTL
                ]
                for k in expired_keys:
                    del _client_cache[k]

            return client
        except ImportError:
            logger.error("anthropic package is not installed")
            raise

    @property
    def client(self):
        """Lazy-load the default Anthropic client (for backward compatibility)."""
        return self._get_client()

    def is_available(self, user_api_key: str | None = None) -> bool:
        """Check if Claude Vision is available.

        Args:
            user_api_key: Optional user-specific API key to check.
        """
        try:
            api_key = user_api_key or self._get_system_api_key()
            return bool(api_key) and settings.use_claude_vision
        except Exception:
            return False

    async def analyze_label(
        self,
        image_data: bytes,
        media_type: str = "image/jpeg",
        user_api_key: str | None = None,
    ) -> dict[str, Any]:
        """Analyze a wine label image using Claude Vision.

        Args:
            image_data: Raw image data as bytes.
            media_type: MIME type of the image (image/jpeg, image/png, etc.)
            user_api_key: Optional user-specific API key.

        Returns:
            Dictionary with parsed wine information.
        """
        try:
            # Encode image to base64
            image_base64 = base64.standard_b64encode(image_data).decode("utf-8")

            # Get client (uses user key if provided, else system key)
            client = self._get_client(user_api_key)

            # Call Claude API with vision
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": WINE_ANALYSIS_PROMPT,
                            },
                        ],
                    }
                ],
            )

            # Extract the response text
            response_text = message.content[0].text

            # Parse JSON from response
            # Handle case where Claude might wrap JSON in markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            result = json.loads(response_text.strip())

            # Parse drink window if present
            drink_window = result.get("drink_window")
            drink_window_start = None
            drink_window_end = None
            if drink_window and isinstance(drink_window, str) and "-" in drink_window:
                parts = drink_window.split("-")
                try:
                    drink_window_start = int(parts[0].strip())
                    drink_window_end = int(parts[1].strip())
                except (ValueError, IndexError):
                    pass

            # Ensure all expected fields exist
            return {
                "name": result.get("name"),
                "winery": result.get("winery"),
                "vintage": result.get("vintage"),
                "grape_variety": result.get("grape_variety"),
                "grape_varieties": result.get("grape_varieties", []),
                "region": result.get("region"),
                "appellation": result.get("appellation"),
                "country": result.get("country"),
                "wine_type": result.get("wine_type"),
                "classification": result.get("classification"),
                "alcohol_percentage": result.get("alcohol_percentage"),
                "drink_window_start": drink_window_start,
                "drink_window_end": drink_window_end,
                "producer_type": result.get("producer_type"),
                "raw_text": result.get("raw_text", ""),
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.debug(f"Response was: {response_text}")
            return self._empty_result()
        except Exception as e:
            logger.error(f"Claude Vision analysis failed: {e}")
            return self._empty_result()

    async def analyze_labels(
        self,
        front_image_data: bytes,
        back_image_data: bytes | None = None,
        front_media_type: str = "image/jpeg",
        back_media_type: str = "image/jpeg",
        user_api_key: str | None = None,
    ) -> dict[str, Any]:
        """Analyze front and back wine label images.

        Args:
            front_image_data: Front label image data.
            back_image_data: Optional back label image data.
            front_media_type: MIME type of front image.
            back_media_type: MIME type of back image.
            user_api_key: Optional user-specific API key.

        Returns:
            Combined analysis results.
        """
        try:
            # Get client (uses user key if provided, else system key)
            client = self._get_client(user_api_key)

            # Build message content with images
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": front_media_type,
                        "data": base64.standard_b64encode(front_image_data).decode("utf-8"),
                    },
                },
                {
                    "type": "text",
                    "text": "Front label:" if back_image_data else WINE_ANALYSIS_PROMPT,
                },
            ]

            if back_image_data:
                content.extend([
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": back_media_type,
                            "data": base64.standard_b64encode(back_image_data).decode("utf-8"),
                        },
                    },
                    {
                        "type": "text",
                        "text": "Back label:",
                    },
                    {
                        "type": "text",
                        "text": WINE_ANALYSIS_PROMPT.replace(
                            "this wine label image",
                            "these wine label images (front and back)"
                        ),
                    },
                ])

            # Call Claude API
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": content}],
            )

            response_text = message.content[0].text

            # Parse JSON
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            result = json.loads(response_text.strip())

            # Parse drink window if present
            drink_window = result.get("drink_window")
            drink_window_start = None
            drink_window_end = None
            if drink_window and isinstance(drink_window, str) and "-" in drink_window:
                parts = drink_window.split("-")
                try:
                    drink_window_start = int(parts[0].strip())
                    drink_window_end = int(parts[1].strip())
                except (ValueError, IndexError):
                    pass

            return {
                "name": result.get("name"),
                "winery": result.get("winery"),
                "vintage": result.get("vintage"),
                "grape_variety": result.get("grape_variety"),
                "grape_varieties": result.get("grape_varieties", []),
                "region": result.get("region"),
                "appellation": result.get("appellation"),
                "country": result.get("country"),
                "wine_type": result.get("wine_type"),
                "classification": result.get("classification"),
                "alcohol_percentage": result.get("alcohol_percentage"),
                "drink_window_start": drink_window_start,
                "drink_window_end": drink_window_end,
                "producer_type": result.get("producer_type"),
                "raw_text": result.get("raw_text", ""),
                "front_label_text": result.get("raw_text", ""),
                "back_label_text": None,  # Combined in raw_text
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            return self._empty_result()
        except Exception as e:
            logger.error(f"Claude Vision analysis failed: {e}")
            return self._empty_result()

    def _empty_result(self) -> dict[str, Any]:
        """Return an empty result dictionary."""
        return {
            "name": None,
            "winery": None,
            "vintage": None,
            "grape_variety": None,
            "grape_varieties": [],
            "region": None,
            "appellation": None,
            "country": None,
            "wine_type": None,
            "classification": None,
            "alcohol_percentage": None,
            "drink_window_start": None,
            "drink_window_end": None,
            "producer_type": None,
            "raw_text": "",
            "front_label_text": "",
            "back_label_text": None,
        }
