"""Column mapping functions for wine imports."""

import json
import logging
import os
from typing import Any

from winebox.config import settings

from .constants import (
    CANONICAL_WINE_FIELDS,
    HEADER_ALIASES,
    VALID_WINE_FIELDS,
    WINE_FIELD_DESCRIPTIONS,
)

logger = logging.getLogger(__name__)


def suggest_column_mapping(headers: list[str]) -> dict[str, str]:
    """Auto-suggest column mapping based on header names.

    Args:
        headers: List of column header names from the spreadsheet.

    Returns:
        Dict mapping header name -> wine field name or "custom:<header>".
    """
    mapping: dict[str, str] = {}
    for header in headers:
        normalized = header.lower().strip()
        if normalized in HEADER_ALIASES:
            mapping[header] = HEADER_ALIASES[normalized]
        else:
            mapping[header] = f"custom:{header}"
    return mapping


def _static_fallback(header: str) -> str:
    """Look up a single header in the static alias table.

    Args:
        header: Column header name.

    Returns:
        Matched wine field name or "custom:<header>".
    """
    normalized = header.lower().strip()
    if normalized in HEADER_ALIASES:
        return HEADER_ALIASES[normalized]
    return f"custom:{header}"


def _build_mapping_prompt(
    headers: list[str],
    preview_rows: list[dict[str, Any]],
) -> str:
    """Build the Claude prompt for AI-assisted column mapping.

    Args:
        headers: Column header names from the spreadsheet.
        preview_rows: Up to 5 sample rows for context.

    Returns:
        Prompt string for the Claude API.
    """
    # Build field list with descriptions
    fields_section = "\n".join(
        f'  - "{field}": {desc}' for field, desc in WINE_FIELD_DESCRIPTIONS.items()
    )

    # Build header + sample values section
    header_sections: list[str] = []
    for header in headers:
        samples = []
        for row in preview_rows[:3]:
            val = row.get(header, "")
            if val:
                samples.append(str(val))
        sample_text = ", ".join(f'"{s}"' for s in samples) if samples else "(no values)"
        header_sections.append(f'  - "{header}": sample values: {sample_text}')
    headers_section = "\n".join(header_sections)

    return f"""You are mapping spreadsheet column headers to wine database fields.

Valid wine fields:
{fields_section}

Special values:
  - "skip": Ignore this column entirely
  - "custom:<name>": Store as a custom field with the given name

Spreadsheet columns (with sample values):
{headers_section}

Instructions:
- Map each column header to the most appropriate wine field, "skip", or "custom:<name>".
- PRIORITY: The following are the core wine fields — try hardest to match these:
  name (REQUIRED), winery, vintage, grape_variety, country, region.
  Rows without "name" mapped will be skipped entirely.
- Consider typos, abbreviations, and non-English headers (French, Italian, Spanish, German, etc.).
- Use sample values to disambiguate ambiguous headers (e.g. "Type" with values "Red", "White" -> "wine_type_id").
- If a column clearly doesn't match any wine field, use "custom:<original header name>".
- Return ONLY a JSON object mapping each header to its target field. No extra text.

Example output:
{{"Wine Name": "name", "Producer": "winery", "Year": "vintage", "Rating": "custom:Rating"}}"""


def _is_valid_mapping_value(value: str) -> bool:
    """Check if a mapping value is valid (known field, "skip", or "custom:...").

    Args:
        value: The mapping target value.

    Returns:
        True if the value is valid.
    """
    if value == "skip":
        return True
    if value.startswith("custom:") and len(value) > 7:
        return True
    return value in VALID_WINE_FIELDS


async def suggest_column_mapping_ai(
    headers: list[str],
    preview_rows: list[dict[str, Any]],
) -> dict[str, str] | None:
    """Suggest column mapping using Claude Haiku for smarter matching.

    Falls back to None if the API key is missing, the call fails, or the
    response can't be parsed. The caller should then use the static
    suggest_column_mapping() instead.

    Args:
        headers: Column header names from the spreadsheet.
        preview_rows: Sample rows (up to 5) for context.

    Returns:
        Dict mapping header -> wine field, or None on failure.
    """
    # Check for API key
    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("No Anthropic API key available, skipping AI mapping")
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = _build_mapping_prompt(headers, preview_rows)

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Handle markdown code blocks (same pattern as vision.py)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        result = json.loads(response_text.strip())

        if not isinstance(result, dict):
            logger.warning("AI mapping returned non-dict: %s", type(result).__name__)
            return None

        # Validate each mapping; fall back to static per-header for invalid ones
        validated: dict[str, str] = {}
        for header in headers:
            ai_value = result.get(header)
            if ai_value and isinstance(ai_value, str) and _is_valid_mapping_value(ai_value):
                validated[header] = ai_value
            else:
                validated[header] = _static_fallback(header)
                if ai_value is not None:
                    logger.debug(
                        "AI mapping for '%s' -> '%s' invalid, using static fallback",
                        header,
                        ai_value,
                    )

        return validated

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse AI mapping response as JSON: %s", e)
        return None
    except Exception as e:
        logger.warning("AI column mapping failed: %s", e)
        return None
