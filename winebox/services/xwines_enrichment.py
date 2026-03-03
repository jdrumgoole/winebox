"""X-Wines enrichment service for auto-filling wine data from the X-Wines dataset.

When checking in a wine via label scan, OCR/Vision extraction often misses fields
(grape variety, region, wine type, etc.). This service searches X-Wines by the
detected wine name and fills in missing fields, while always preserving
label-detected values as the source of truth.
"""

import ast
import asyncio
import logging
import re
import unicodedata

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

    # Fill in missing fields from X-Wines match, tracking which ones we enrich
    enriched_fields: list[str] = []
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
            enriched_fields.append(parsed_key)

    # Add xwines_id and enriched_fields so the frontend knows what was enriched
    parsed["xwines_id"] = match.xwines_id
    if enriched_fields:
        parsed["enriched_fields"] = enriched_fields

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


# ---------------------------------------------------------------------------
# Batch enrichment (one Atlas Search per chunk instead of one per row)
# ---------------------------------------------------------------------------

# Concurrency limiter for individual fallback queries (regex path)
_ENRICHMENT_SEMAPHORE = asyncio.Semaphore(10)


def _normalize(s: str) -> str:
    """Normalize string for fuzzy comparison (lowercase, strip accents)."""
    s = s.lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _score_candidate(query_name: str, candidate: XWinesWine) -> float:
    """Score how well a candidate matches a query wine name.

    Returns a float score; higher is better.  0 means no match.
    """
    q = _normalize(query_name)
    q_terms = set(q.split())
    c_name = _normalize(candidate.name or "")
    c_winery = _normalize(candidate.winery_name or "")
    score = 0.0

    # Exact name match
    if c_name == q:
        score += 100
    # Candidate name starts with query
    elif c_name.startswith(q):
        score += 50
    # Query contained in candidate name
    elif q in c_name:
        score += 30
    # Candidate name contained in query
    elif c_name in q:
        score += 20

    # Term overlap (both name and winery)
    if q_terms:
        matched = sum(1 for t in q_terms if t in c_name or t in c_winery)
        score += 10 * (matched / len(q_terms))

    # Popularity tiebreaker (capped)
    score += min((candidate.rating_count or 0) / 10000, 5)

    return score


async def _find_best_xwines_matches_batch(
    names: list[str],
) -> dict[str, XWinesWine | None]:
    """Find best X-Wines matches for multiple wine names in one query.

    Uses a single Atlas Search query with a should clause per unique name,
    then matches candidates to input names using Python-side scoring.
    Falls back to individual concurrent queries if Atlas Search is unavailable.

    Args:
        names: List of wine names (may contain duplicates or short strings).

    Returns:
        Dict mapping each input name -> best matching XWinesWine or None.
    """
    unique_names = list({n.strip() for n in names if n and len(n.strip()) >= 2})
    if not unique_names:
        return {n: None for n in names}

    # --- Try batch Atlas Search first ---
    try:
        db = get_database()
        collection = db["xwines_wines"]

        should_clauses: list[dict] = []
        for name in unique_names:
            should_clauses.append({
                "text": {
                    "query": name,
                    "path": ["name", "winery_name"],
                    "fuzzy": {"maxEdits": 1, "prefixLength": 2},
                }
            })
            # Boost exact phrase matches for better candidate ranking
            should_clauses.append({
                "phrase": {
                    "query": name,
                    "path": "name",
                    "score": {"boost": {"value": 5}},
                }
            })

        candidate_limit = min(len(unique_names) * 3, 500)
        pipeline: list[dict] = [
            {
                "$search": {
                    "index": "xwines_search",
                    "compound": {
                        "should": should_clauses,
                        "minimumShouldMatch": 1,
                    },
                }
            },
            {"$addFields": {"searchScore": {"$meta": "searchScore"}}},
            {"$sort": {"searchScore": -1, "rating_count": -1}},
            {"$limit": candidate_limit},
        ]
        docs = await collection.aggregate(pipeline).to_list(length=candidate_limit)

        if docs:
            candidates: list[XWinesWine] = []
            for doc in docs:
                try:
                    wine = XWinesWine(
                        **{k: v for k, v in doc.items() if k not in ("_id", "searchScore")}
                    )
                    candidates.append(wine)
                except Exception:
                    continue

            # Assign best candidate to each input name
            results: dict[str, XWinesWine | None] = {}
            for name in names:
                name_stripped = name.strip() if name else ""
                if len(name_stripped) < 2:
                    results[name] = None
                    continue
                best: XWinesWine | None = None
                best_score = 0.0
                for c in candidates:
                    s = _score_candidate(name_stripped, c)
                    if s > best_score:
                        best_score = s
                        best = c
                # Require minimum score to avoid false positives
                results[name] = best if best_score >= 10 else None
            return results

        return {n: None for n in names}

    except Exception as e:
        logger.debug("Batch Atlas Search failed, falling back to individual: %s", e)

    # --- Fallback: individual queries with concurrency limiter ---
    async def _lookup(name: str) -> tuple[str, XWinesWine | None]:
        async with _ENRICHMENT_SEMAPHORE:
            match = await _find_best_xwines_match(name)
            return (name, match)

    tasks = [_lookup(n) for n in unique_names]
    lookup_results = await asyncio.gather(*tasks, return_exceptions=True)

    name_to_match: dict[str, XWinesWine | None] = {}
    for result in lookup_results:
        if isinstance(result, Exception):
            continue
        name_to_match[result[0]] = result[1]

    return {n: name_to_match.get(n.strip() if n else "", None) for n in names}


async def enrich_batch_with_xwines(parsed_list: list[dict]) -> None:
    """Enrich multiple parsed wine dicts with X-Wines data in a single batch.

    Uses one Atlas Search query for all names, then applies enrichment
    to each dict in-place.  Silently skips failures.

    Args:
        parsed_list: List of parsed wine dicts (modified in-place).
    """
    names = [str(p.get("name", "")).strip() for p in parsed_list]

    try:
        matches = await _find_best_xwines_matches_batch(names)
    except Exception as e:
        logger.warning("Batch X-Wines enrichment failed: %s", e)
        return

    for parsed, name in zip(parsed_list, names):
        match = matches.get(name)
        if not match:
            continue

        enriched_fields: list[str] = []
        for parsed_key, xwines_attr, transform in _FIELD_MAP:
            if parsed.get(parsed_key):
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
                enriched_fields.append(parsed_key)

        parsed["xwines_id"] = match.xwines_id
        if enriched_fields:
            parsed["enriched_fields"] = enriched_fields
