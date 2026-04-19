"""Reference-data enrichment: ask Claude for a drinkability estimate per X-Wines wine.

The estimate is keyed to the wine's *release* (not vintage) so a single
estimate is shared by every user who owns a bottle of that reference wine.
The result is persisted on `XWinesWine.drinkability` and later vintage-
adjusted into a `DrinkabilityWindow` per user wine.

Pattern mirrors `background_enrichment.enrich_unenriched_wines`:
- Stream candidates in fixed-size batches.
- One Anthropic call per batch.
- `bulk_write` of `UpdateOne` ops back to the collection.

Costs: at the trial-validated rate of ~$1.74 per 1000 reference wines on
Sonnet 4.5, a 100-wine smoke run is ~$0.17.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from pymongo import UpdateOne

from winebox.config import settings
from winebox.database import get_database
from winebox.models.drinkability import DrinkabilityConfidence, DrinkabilityEstimate

logger = logging.getLogger(__name__)

ENRICHMENT_BATCH_SIZE = 50

# Released-relative drinkability prompt, derived from the trial script.
# We deliberately omit the trial's `recommendation` field — that's a function
# of (estimate, current year, vintage) and is computed at read time by
# `compute_status`, not stored on the reference wine.
_PROMPT_HEADER = """You are a wine expert estimating drinkability windows for wines.

For each numbered wine below, estimate:
  - peak_years_from_release: [min, max] — years from release when the wine is at its best
  - drinkable_until_years: integer — years from release after which the wine is past its prime
  - confidence: "high" | "medium" | "low" — based on how much the wine's data supports the estimate
  - reasoning: one short sentence explaining the choice

Consider grape variety (Cabernet ages longer than Pinot Noir, Riesling longer than Sauvignon Blanc),
body (full-bodied ages longer), acidity (higher acidity = longer aging), region typical styles,
and rating/popularity as a quality proxy.

Respond with ONLY a JSON object keyed by wine number (as a string), no prose, no markdown:
{"1": {"peak_years_from_release": [3, 10], "drinkable_until_years": 15,
       "confidence": "high", "reasoning": "..."}, ...}

WINES:
"""


def _fmt(value: Any, placeholder: str = "unknown") -> str:
    if value is None or value == "":
        return placeholder
    return str(value)


def build_prompt(wines: list[dict[str, Any]]) -> str:
    """Render a batch of XWinesWine docs as the user prompt for Claude."""
    lines = [_PROMPT_HEADER]
    for i, w in enumerate(wines, 1):
        abv = w.get("abv")
        abv_str = f"{abv}%" if abv is not None else "unknown ABV"
        rating = w.get("avg_rating")
        rating_count = w.get("rating_count") or 0
        rating_str = (
            f"{rating} ({rating_count} reviews)" if rating
            else f"no rating ({rating_count} reviews)"
        )
        lines.append(
            f"{i}. {_fmt(w.get('name'))} by {_fmt(w.get('winery_name'), 'unknown winery')}, "
            f"{_fmt(w.get('wine_type'))}, grapes: {_fmt(w.get('grapes'), 'unknown grape')}, "
            f"region: {_fmt(w.get('region_name'), 'unknown region')}, "
            f"{_fmt(w.get('country'), 'unknown country')}, "
            f"ABV: {abv_str}, body: {_fmt(w.get('body'), 'unknown body')}, "
            f"acidity: {_fmt(w.get('acidity'), 'unknown acidity')}, "
            f"rating: {rating_str}"
        )
    return "\n".join(lines)


def parse_response(text: str) -> dict[str, dict[str, Any]]:
    """Strip markdown fences and parse JSON. Returns {} on failure."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.startswith("json"):
                candidate = candidate[4:]
            text = candidate.strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON from Claude: %s", e)
        logger.debug("Raw response head: %s", text[:500])
        return {}
    return result if isinstance(result, dict) else {}


def _coerce_estimate(
    rec: dict[str, Any], model: str
) -> DrinkabilityEstimate | None:
    """Convert one parsed Claude record into a `DrinkabilityEstimate`.

    Returns None if the record is missing fields, has nonsensical bounds,
    or fails Pydantic validation. Logging happens at the caller so we can
    point at which xwines_id failed.
    """
    peak = rec.get("peak_years_from_release")
    if not (isinstance(peak, list) and len(peak) == 2):
        return None
    try:
        peak_min = int(peak[0])
        peak_max = int(peak[1])
        until = int(rec.get("drinkable_until_years"))
    except (TypeError, ValueError):
        return None
    if peak_min > peak_max or until < peak_max:
        return None

    confidence_raw = (rec.get("confidence") or "").lower()
    try:
        confidence = DrinkabilityConfidence(confidence_raw)
    except ValueError:
        return None
    # We don't accept user_override from Claude — it's reserved for manual entry.
    if confidence == DrinkabilityConfidence.USER_OVERRIDE:
        return None

    reasoning = rec.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        return None

    try:
        return DrinkabilityEstimate(
            peak_years_from_release_min=peak_min,
            peak_years_from_release_max=peak_max,
            drinkable_until_years=until,
            confidence=confidence,
            reasoning=reasoning.strip()[:500],
            model_used=model[:100],
        )
    except Exception as e:  # pydantic validation error
        logger.debug("Estimate validation failed: %s", e)
        return None


async def estimate_drinkability_batch(
    xwines_docs: list[dict[str, Any]],
    model: str = "claude-sonnet-4-5",
) -> dict[int, DrinkabilityEstimate]:
    """Send one batch of X-Wines docs to Claude and return estimates by xwines_id.

    Each input dict must include `xwines_id`; missing/invalid responses are
    silently skipped (the caller treats them as "try again next run").
    """
    if not xwines_docs:
        return {}
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed; skipping drinkability batch")
        return {}

    api_key = settings.anthropic_api_key
    if not api_key:
        logger.warning("WINEBOX_ANTHROPIC_API_KEY not set; skipping drinkability batch")
        return {}

    prompt = build_prompt(xwines_docs)
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=120.0)
    try:
        message = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.warning("Drinkability batch call failed: %s", e)
        return {}

    if not message.content:
        return {}
    raw = message.content[0].text
    parsed = parse_response(raw)
    usage = getattr(message, "usage", None)
    if usage is not None:
        in_tok = getattr(usage, "input_tokens", 0)
        out_tok = getattr(usage, "output_tokens", 0)
        logger.info(
            "drinkability batch tokens: in=%d out=%d (n=%d, model=%s)",
            in_tok, out_tok, len(xwines_docs), model,
        )

    results: dict[int, DrinkabilityEstimate] = {}
    for i, doc in enumerate(xwines_docs, 1):
        rec = parsed.get(str(i))
        if not rec:
            continue
        estimate = _coerce_estimate(rec, model=model)
        if estimate is None:
            logger.debug("Skipping xwines_id=%s — invalid response", doc.get("xwines_id"))
            continue
        results[int(doc["xwines_id"])] = estimate
    return results


async def enrich_xwines_drinkability(
    limit: int | None = None,
    model: str = "claude-sonnet-4-5",
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """Find XWinesWine docs missing `drinkability`, batch-estimate, write back.

    `limit` caps the *total* number of docs considered (not per batch),
    making it cheap to do small smoke runs (`--limit 100` ≈ $0.17).

    Returns counts: {"considered", "enriched", "failed"}.
    """
    db = get_database()
    col = db["xwines_wines"]

    base_filter: dict[str, Any] = {"drinkability": None}
    total_remaining = await col.count_documents(base_filter)
    target = min(limit, total_remaining) if limit is not None else total_remaining
    if target == 0:
        return {"considered": 0, "enriched": 0, "failed": 0}

    enriched = 0
    failed = 0
    considered = 0

    projection = {
        "xwines_id": 1, "name": 1, "winery_name": 1, "wine_type": 1,
        "grapes": 1, "region_name": 1, "country": 1, "abv": 1,
        "body": 1, "acidity": 1, "avg_rating": 1, "rating_count": 1,
    }

    while considered < target:
        batch_cap = min(ENRICHMENT_BATCH_SIZE, target - considered)
        cursor = col.find(base_filter, projection).sort("_id", 1).limit(batch_cap)
        batch = await cursor.to_list(length=batch_cap)
        if not batch:
            break

        try:
            estimates = await estimate_drinkability_batch(batch, model=model)
        except Exception as e:
            logger.warning("Drinkability batch failed: %s", e)
            failed += len(batch)
            considered += len(batch)
            if progress_callback:
                progress_callback(enriched, target)
            continue

        bulk_ops: list[UpdateOne] = []
        for doc in batch:
            xid = doc.get("xwines_id")
            estimate = estimates.get(int(xid)) if xid is not None else None
            if estimate is None:
                failed += 1
                continue
            bulk_ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {"drinkability": estimate.model_dump(mode="json")}},
                )
            )

        if bulk_ops:
            try:
                result = await col.bulk_write(bulk_ops, ordered=False)
                enriched += result.modified_count
            except Exception as e:
                logger.warning("Drinkability bulk_write failed: %s", e)
                failed += len(bulk_ops)

        considered += len(batch)
        if progress_callback:
            progress_callback(enriched, target)
        await asyncio.sleep(0)

    return {"considered": considered, "enriched": enriched, "failed": failed}
