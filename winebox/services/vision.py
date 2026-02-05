"""Claude Vision service for wine label analysis."""

import base64
import json
import logging
import os
from typing import Any

from winebox.config import settings

logger = logging.getLogger(__name__)

WINE_ANALYSIS_PROMPT = """Analyze this wine label image and extract the following information.
Return ONLY a valid JSON object with these fields (use null for any field you cannot determine):

{
    "name": "The wine name/title",
    "winery": "The winery or producer name",
    "vintage": 2020,
    "grape_variety": "The grape variety (e.g., Cabernet Sauvignon, Chardonnay)",
    "region": "The wine region (e.g., Napa Valley, Bordeaux)",
    "country": "The country of origin",
    "alcohol_percentage": 13.5,
    "raw_text": "All readable text from the label, preserving line breaks"
}

Important:
- vintage should be a number (year) or null
- alcohol_percentage should be a number or null
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
        """Get an Anthropic client, using user key if provided, else system key."""
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

            # Create a new client for user-specific key
            return anthropic.Anthropic(api_key=api_key)
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

            # Ensure all expected fields exist
            return {
                "name": result.get("name"),
                "winery": result.get("winery"),
                "vintage": result.get("vintage"),
                "grape_variety": result.get("grape_variety"),
                "region": result.get("region"),
                "country": result.get("country"),
                "alcohol_percentage": result.get("alcohol_percentage"),
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

            return {
                "name": result.get("name"),
                "winery": result.get("winery"),
                "vintage": result.get("vintage"),
                "grape_variety": result.get("grape_variety"),
                "region": result.get("region"),
                "country": result.get("country"),
                "alcohol_percentage": result.get("alcohol_percentage"),
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
            "region": None,
            "country": None,
            "alcohol_percentage": None,
            "raw_text": "",
            "front_label_text": "",
            "back_label_text": None,
        }
