"""Claude-powered wine matching service for X-Wines enrichment.

Uses Claude Haiku to re-rank Atlas Search candidates, providing smarter
matching for composite/ambiguous wine names than the hand-tuned scoring function.
"""

import json
import logging
import os
from typing import Any

from winebox.config import settings

logger = logging.getLogger(__name__)

MATCHING_PROMPT = """You are a wine expert matching wine names to a reference database.

For each numbered query below, examine the candidate wines and pick the BEST match.
Return the candidate number (1-indexed within that query's candidates), or null if none match well.

Consider:
- Winery/producer names embedded in the query
- Region, appellation, and country context
- Wine classifications (Grand Cru, Reserva, etc.)
- Wine type consistency (don't match a red to a white)
- Vintage is NOT a factor for matching (same wine, different years = match)

Respond with ONLY a JSON object mapping query numbers to chosen candidate numbers (or null):
{"1": 2, "2": null, "3": 1}

QUERIES AND CANDIDATES:
"""


def _build_prompt(
    queries: list[str],
    candidates_per_query: dict[str, list[dict[str, Any]]],
) -> str:
    """Build the structured prompt for Claude matching.

    Args:
        queries: List of wine name queries.
        candidates_per_query: Dict mapping query name -> list of candidate dicts.
            Each candidate dict should have at minimum 'name' and optionally
            'winery_name', 'region_name', 'country', 'wine_type'.

    Returns:
        The full prompt string.
    """
    lines = [MATCHING_PROMPT]

    for i, query in enumerate(queries, 1):
        lines.append(f"Query {i}: \"{query}\"")
        candidates = candidates_per_query.get(query, [])
        if not candidates:
            lines.append("  (no candidates)")
        else:
            for j, c in enumerate(candidates, 1):
                parts = [c.get("name", "unknown")]
                if c.get("winery_name"):
                    parts.append(f"by {c['winery_name']}")
                if c.get("region_name"):
                    parts.append(f"from {c['region_name']}")
                if c.get("country"):
                    parts.append(f"({c['country']})")
                if c.get("wine_type"):
                    parts.append(f"[{c['wine_type']}]")
                lines.append(f"  {j}. {' '.join(parts)}")
        lines.append("")

    return "\n".join(lines)


def _parse_response(response_text: str, num_queries: int) -> dict[str, int | None]:
    """Parse Claude's JSON response into a query-index -> candidate-index mapping.

    Args:
        response_text: Raw text response from Claude.
        num_queries: Number of queries sent.

    Returns:
        Dict mapping query number (str) -> candidate index (1-based int) or None.
    """
    # Strip markdown code blocks if present
    text = response_text.strip()
    if text.startswith("```"):
        # Remove opening ```json or ``` and closing ```
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Claude matcher returned invalid JSON: %s", text[:200])
        return {}

    if not isinstance(parsed, dict):
        logger.warning("Claude matcher returned non-dict JSON: %s", type(parsed))
        return {}

    result: dict[str, int | None] = {}
    for key, value in parsed.items():
        if value is None:
            result[str(key)] = None
        elif isinstance(value, int) and value >= 1:
            result[str(key)] = value
        else:
            # Skip invalid entries
            continue

    return result


async def match_wines_batch(
    queries: list[str],
    candidates_per_query: dict[str, list[dict[str, Any]]],
) -> dict[str, int | None]:
    """Use Claude to match wine queries to their best candidates.

    Args:
        queries: List of wine name strings to match.
        candidates_per_query: Dict mapping each query string to a list of
            candidate dicts with keys like 'name', 'winery_name', etc.

    Returns:
        Dict mapping each query string to the 1-based index of the best
        candidate, or None if no good match. Returns empty dict on failure.
    """
    if not queries:
        return {}

    # Filter out queries with no candidates
    active_queries = [q for q in queries if candidates_per_query.get(q)]
    if not active_queries:
        return {q: None for q in queries}

    # Check if Claude matching is enabled
    if not settings.use_claude_matching:
        logger.debug("Claude matching disabled by config")
        return {}

    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("No Anthropic API key available for Claude matching")
        return {}

    prompt = _build_prompt(active_queries, candidates_per_query)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
        message = client.messages.create(
            model=settings.claude_matching_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text
        raw_result = _parse_response(response_text, len(active_queries))

        # Map query indices back to query strings
        result: dict[str, int | None] = {}
        for i, query in enumerate(active_queries, 1):
            result[query] = raw_result.get(str(i))

        # Fill in queries that had no candidates
        for q in queries:
            if q not in result:
                result[q] = None

        return result

    except ImportError:
        logger.warning("anthropic package not installed, Claude matching unavailable")
        return {}
    except Exception as e:
        logger.warning("Claude matching failed: %s", e)
        return {}
