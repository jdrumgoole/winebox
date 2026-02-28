"""X-Wines enrichment service for auto-filling wine data from the X-Wines dataset.

When checking in a wine via label scan, OCR/Vision extraction often misses fields
(grape variety, region, wine type, etc.). This service searches X-Wines by the
detected wine name and fills in missing fields, while always preserving
label-detected values as the source of truth.
"""

import ast
import logging
import re

from winebox.database import get_database
from winebox.models import XWinesWine

logger = logging.getLogger(__name__)

# Field mapping: parsed dict key -> (XWinesWine attribute, optional transform)
_FIELD_MAP: list[tuple[str, str, str | None]] = [
    # (parsed_key, xwines_attr, transform)
    ("winery", "winery_name", None),
    ("grape_variety", "grapes", "grapes"),
    ("region", "region_name", None),
    ("country", "country", None),
    ("alcohol_percentage", "abv", None),
    ("wine_type", "wine_type", "lowercase"),
]


def parse_xwines_grapes(grapes_str: str | None) -> str | None:
    """Parse X-Wines grapes field into a comma-separated string.

    Handles Python-style single-quoted lists and JSON-style double-quoted lists:
      "['Merlot', 'Cabernet Sauvignon']" -> "Merlot, Cabernet Sauvignon"

    Args:
        grapes_str: Raw grapes string from X-Wines, or None.

    Returns:
        Comma-separated grape names, or None for empty/invalid input.
    """
    if not grapes_str or not grapes_str.strip():
        return None

    # Try Python literal eval first (handles single quotes)
    try:
        parsed = ast.literal_eval(grapes_str)
        if isinstance(parsed, list):
            result = ", ".join(str(g) for g in parsed if g)
            return result if result else None
    except (ValueError, SyntaxError):
        pass

    # Try replacing single quotes with double quotes for JSON parsing
    import json

    try:
        fixed = grapes_str.replace("'", '"')
        parsed = json.loads(fixed)
        if isinstance(parsed, list):
            result = ", ".join(str(g) for g in parsed if g)
            return result if result else None
    except (json.JSONDecodeError, ValueError):
        pass

    # If it's already a plain string (not a list), return as-is
    stripped = grapes_str.strip()
    if stripped and not stripped.startswith("["):
        return stripped

    return None


async def enrich_parsed_with_xwines(parsed: dict) -> dict:
    """Enrich parsed wine data with X-Wines reference data.

    Searches X-Wines by wine name (if present and >= 2 chars), takes the top-1
    result by popularity, and fills in any missing fields.

    Label-detected values are always preserved as the source of truth —
    only empty/falsy fields are filled from X-Wines.

    Args:
        parsed: Dict of parsed wine data (e.g. from OCR/Vision).

    Returns:
        The (potentially enriched) parsed dict with xwines_id added on match.
    """
    name = parsed.get("name")
    if not name or len(str(name).strip()) < 2:
        return parsed

    name = str(name).strip()

    try:
        match = await _find_best_xwines_match(name)
    except Exception as e:
        logger.warning("X-Wines enrichment lookup failed: %s", e)
        return parsed

    if not match:
        return parsed

    # Fill in missing fields from X-Wines match
    for parsed_key, xwines_attr, transform in _FIELD_MAP:
        if parsed.get(parsed_key):
            # Preserve existing (label-detected) value
            continue

        xwines_value = getattr(match, xwines_attr, None)
        if not xwines_value:
            continue

        if transform == "grapes":
            xwines_value = parse_xwines_grapes(str(xwines_value))
        elif transform == "lowercase":
            xwines_value = str(xwines_value).lower()

        if xwines_value:
            parsed[parsed_key] = xwines_value

    # Add xwines_id so the frontend knows a match was found
    parsed["xwines_id"] = match.xwines_id

    return parsed


async def _find_best_xwines_match(name: str) -> XWinesWine | None:
    """Find the best matching X-Wines wine by name.

    Uses Atlas Search when available, requiring ALL search terms to match
    (AND logic) to eliminate false positives. Falls back to three-tier regex
    search for local dev. Returns the top-1 result, prioritizing exact phrase
    matches over fuzzy matches.

    Args:
        name: Wine name to search for.

    Returns:
        Best matching XWinesWine, or None if no match found.
    """
    terms = name.split()

    # Try Atlas Search first with AND logic for all terms
    try:
        db = get_database()
        collection = db["xwines_wines"]

        # Build must clauses - require ALL terms to appear (AND logic)
        must_clauses: list[dict] = [
            {
                "text": {
                    "query": term,
                    "path": ["name", "winery_name"],
                    "fuzzy": {"maxEdits": 1, "prefixLength": 2},
                }
            }
            for term in terms
        ]

        # Use compound query with must for AND logic, should for score boosting
        pipeline: list[dict] = [
            {
                "$search": {
                    "index": "xwines_search",
                    "compound": {
                        "must": must_clauses,
                        "should": [
                            # Boost exact phrase matches in name
                            {
                                "phrase": {
                                    "query": name,
                                    "path": "name",
                                    "score": {"boost": {"value": 10}},
                                }
                            },
                            # Boost phrase matches in winery_name
                            {
                                "phrase": {
                                    "query": name,
                                    "path": "winery_name",
                                    "score": {"boost": {"value": 5}},
                                }
                            },
                        ],
                    },
                }
            },
            {"$addFields": {"searchScore": {"$meta": "searchScore"}}},
            {"$sort": {"searchScore": -1, "rating_count": -1}},
            {"$limit": 1},
        ]
        docs = await collection.aggregate(pipeline).to_list(length=1)
        if docs:
            # Convert raw doc to XWinesWine model
            doc = docs[0]
            return XWinesWine(**{k: v for k, v in doc.items() if k not in ("_id", "searchScore")})
    except Exception as e:
        logger.debug("Atlas Search unavailable for enrichment, falling back to regex: %s", e)

    # Fallback: three-tier regex search with AND logic
    escaped_name = re.escape(name)

    # Tier 1: Full phrase at START of name (highest priority)
    start_pattern = re.compile(f"^{escaped_name}", re.IGNORECASE)
    match = await XWinesWine.find({"name": {"$regex": start_pattern}}).sort(
        [("rating_count", -1)]
    ).first_or_none()
    if match:
        return match

    # Tier 2: Full phrase with word boundaries anywhere
    word_boundary_pattern = re.compile(rf"\b{escaped_name}\b", re.IGNORECASE)
    match = await XWinesWine.find(
        {
            "$or": [
                {"name": {"$regex": word_boundary_pattern}},
                {"winery_name": {"$regex": word_boundary_pattern}},
            ]
        }
    ).sort([("rating_count", -1)]).first_or_none()
    if match:
        return match

    # Tier 3: All terms present as substrings (AND logic)
    term_conditions = []
    for term in terms:
        term_pattern = re.compile(re.escape(term), re.IGNORECASE)
        term_conditions.append(
            {
                "$or": [
                    {"name": {"$regex": term_pattern}},
                    {"winery_name": {"$regex": term_pattern}},
                ]
            }
        )

    if len(term_conditions) > 1:
        all_terms_condition: dict = {"$and": term_conditions}
    else:
        all_terms_condition = term_conditions[0]

    match = await XWinesWine.find(all_terms_condition).sort(
        [("rating_count", -1)]
    ).first_or_none()

    return match
