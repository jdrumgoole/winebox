#!/usr/bin/env python3
"""Annotate X-Wines dataset with estimated retail prices using Claude.

Standalone script that uses the Anthropic API (Claude Haiku) to estimate
retail prices for wines in the xwines_wines collection. Results are stored
in a separate xwines_prices collection to keep reference data clean.

Uses pymongo directly (not the ODM) following the pattern of
deploy/import_xwines_mongo.py.

Usage:
    uv run python scripts/annotate_xwines_prices.py [OPTIONS]

Examples:
    uv run python scripts/annotate_xwines_prices.py --dry-run --max-wines 100
    uv run python scripts/annotate_xwines_prices.py --max-wines 20
    uv run python scripts/annotate_xwines_prices.py --status
    uv run python scripts/annotate_xwines_prices.py --estimate-cost
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient

logger = logging.getLogger(__name__)

# Price tier definitions
PRICE_TIERS = {
    "budget": (0, 15),
    "value": (15, 25),
    "mid_range": (25, 50),
    "premium": (50, 100),
    "luxury": (100, 250),
    "ultra_premium": (250, float("inf")),
}

VALID_TIERS = set(PRICE_TIERS.keys())
VALID_CONFIDENCES = {"high", "medium", "low"}

SYSTEM_PROMPT = """You are a wine pricing expert. Your task is to estimate typical \
US retail prices (not auction, not wholesale) for wines based on their name, producer, \
region, grape variety, vintage, and other attributes.

Guidelines:
- Prices should reflect current US retail market (wine shop / online retailer)
- Base your estimates on known retail prices from sources like Wine-Searcher, \
Wine.com, Total Wine, and other major US retailers
- Consider the producer's reputation, region prestige, classification, and vintage quality
- Vintage matters significantly: older vintages of prestigious wines cost more; \
great vintage years command premiums (e.g. 2005, 2009, 2010 Bordeaux); \
very recent vintages of age-worthy wines may be cheaper on release
- For unknown or obscure wines, use regional averages as a baseline
- Be conservative with confidence ratings — use "high" only for well-known wines \
where you are certain of the typical retail price
- price_tier definitions: budget (<$15), value ($15-25), mid_range ($25-50), \
premium ($50-100), luxury ($100-250), ultra_premium (>$250)

Each item in the batch specifies a wine AND a vintage year. Price each wine-vintage \
combination individually — the same wine in different vintages should have different prices."""


def get_mongodb_url() -> str:
    """Get MongoDB connection URL from environment or secrets.env."""
    url = os.environ.get("WINEBOX_MONGODB_URL")
    if url:
        return url

    # Check secrets.env in standard locations
    for secrets_path in [
        Path.cwd() / ".env",
        Path.cwd() / "secrets.env",
        Path.home() / ".config" / "winebox" / "secrets.env",
        Path("/opt/winebox/secrets.env"),
    ]:
        if secrets_path.exists():
            for line in secrets_path.read_text().splitlines():
                if line.startswith("WINEBOX_MONGODB_URL="):
                    value = line.split("=", 1)[1].strip()
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    return value

    return "mongodb://localhost:27017"


def get_anthropic_api_key() -> str | None:
    """Get Anthropic API key from environment or secrets.env."""
    key = os.environ.get("WINEBOX_ANTHROPIC_API_KEY") or os.environ.get(
        "ANTHROPIC_API_KEY"
    )
    if key:
        return key

    for secrets_path in [
        Path.cwd() / ".env",
        Path.cwd() / "secrets.env",
        Path.home() / ".config" / "winebox" / "secrets.env",
        Path("/opt/winebox/secrets.env"),
    ]:
        if secrets_path.exists():
            for line in secrets_path.read_text().splitlines():
                if line.startswith("WINEBOX_ANTHROPIC_API_KEY="):
                    value = line.split("=", 1)[1].strip()
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    return value

    return None


def build_batch_prompt(items: list[dict[str, Any]]) -> str:
    """Build the user prompt for a batch of wine-vintage items.

    Args:
        items: List of dicts with wine data + "vintage" key (int or None).

    Returns:
        Formatted prompt string.
    """
    lines = [
        "Estimate retail prices for these wine-vintage combinations. For each, provide:",
        '- price_low / price_high (USD, numbers only)',
        '- confidence: "high" | "medium" | "low"',
        '- price_tier: "budget" (<$15) | "value" ($15-25) | "mid_range" ($25-50) '
        '| "premium" ($50-100) | "luxury" ($100-250) | "ultra_premium" (>$250)',
        "- note: 1-sentence justification mentioning vintage quality if relevant",
        "",
        "Return ONLY a JSON array, one object per item, same order as listed.",
        "Each object: {\"price_low\": N, \"price_high\": N, \"confidence\": \"...\", "
        "\"price_tier\": \"...\", \"note\": \"...\"}",
        "",
        "Wines:",
    ]

    for i, item in enumerate(items, 1):
        parts = [item.get("name", "Unknown")]

        vintage = item.get("vintage")
        if vintage is not None:
            parts.append(f"| Vintage: {vintage}")

        winery = item.get("winery_name")
        if winery:
            parts.append(f"| {winery}")

        wine_type = item.get("wine_type")
        if wine_type:
            parts.append(f"| {wine_type}")

        region = item.get("region_name")
        country = item.get("country")
        location = ", ".join(filter(None, [region, country]))
        if location:
            parts.append(f"| {location}")

        grapes = item.get("grapes")
        if grapes:
            parts.append(f"| {grapes}")

        abv = item.get("abv")
        if abv:
            parts.append(f"| {abv}%")

        avg_rating = item.get("avg_rating")
        rating_count = item.get("rating_count", 0)
        if avg_rating is not None:
            parts.append(f"| Rating: {avg_rating} ({rating_count})")

        # Include Kaggle price context if available
        kaggle_ctx = item.get("_kaggle_context")
        if kaggle_ctx:
            ctx_prices = [f"${c['price_usd']:.0f}" for c in kaggle_ctx if c.get("price_usd")]
            if ctx_prices:
                parts.append(f"| Reference prices from same winery/region: {', '.join(ctx_prices)}")

        lines.append(f"{i}. {' '.join(parts)}")

    return "\n".join(lines)


def parse_response(response_text: str) -> list[dict[str, Any]] | None:
    """Parse Claude's JSON response into a list of price estimates.

    Handles markdown code block wrapping.

    Args:
        response_text: Raw text response from Claude.

    Returns:
        List of price dicts, or None on parse failure.
    """
    text = response_text.strip()

    # Strip markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
        else:
            text = parts[0]

    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, list):
        return None

    return parsed


def validate_price_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize a single price entry from Claude's response.

    Args:
        entry: Raw dict from Claude's JSON response.

    Returns:
        Validated dict with normalized fields, or None if invalid.
    """
    try:
        price_low = float(entry.get("price_low", 0))
        # Handle common LLM typo: "price_height" instead of "price_high"
        price_high = float(
            entry.get("price_high") or entry.get("price_height") or 0
        )
    except (TypeError, ValueError):
        return None

    if price_low <= 0 or price_high <= 0 or price_low > price_high:
        return None

    confidence = str(entry.get("confidence", "")).lower()
    if confidence not in VALID_CONFIDENCES:
        confidence = "low"

    price_tier = str(entry.get("price_tier", "")).lower()
    if price_tier not in VALID_TIERS:
        # Infer tier from midpoint price
        midpoint = (price_low + price_high) / 2
        for tier, (lo, hi) in PRICE_TIERS.items():
            if lo <= midpoint < hi:
                price_tier = tier
                break

    note = str(entry.get("note", ""))[:500]  # Cap length

    return {
        "price_low_usd": round(price_low, 2),
        "price_high_usd": round(price_high, 2),
        "price_tier": price_tier,
        "confidence": confidence,
        "note": note,
    }


class PriceAnnotator:
    """Manages the batch annotation of X-Wines with price estimates."""

    def __init__(
        self,
        *,
        batch_size: int = 20,
        model: str = "claude-haiku-4-5-20251001",
        max_wines: int | None = None,
        min_ratings: int = 0,
        grape: str | None = None,
        priority: str = "popular",
        concurrency: int = 3,
        dry_run: bool = False,
        database: str | None = None,
        verbose: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.model = model
        self.max_wines = max_wines
        self.min_ratings = min_ratings
        self.grape = grape
        self.priority = priority
        self.concurrency = concurrency
        self.dry_run = dry_run
        self.verbose = verbose

        # MongoDB setup
        self.mongo_url = get_mongodb_url()
        self.db_name = database or os.environ.get("WINEBOX_DATABASE", "winebox_oat")
        self.client: MongoClient = MongoClient(self.mongo_url)
        self.db = self.client[self.db_name]
        self.wines_col = self.db["xwines_wines"]
        self.prices_col = self.db["xwines_prices"]
        self.kaggle_col = self.db["kaggle_wine_prices"]

        # Anthropic client (lazy)
        self._anthropic_client = None

        # Rate limiter: minimum interval between API requests (seconds)
        # Default 50 req/min limit → 2.0s between requests for comfortable headroom
        self._rate_lock = threading.Lock()
        self._last_request_time = 0.0
        self._min_request_interval = 2.0  # seconds between requests (~30 req/min)

        # Stats (protected by lock for thread safety)
        self._lock = threading.Lock()
        self.processed = 0
        self.succeeded = 0
        self.failed = 0
        self.skipped = 0
        self.kaggle_matched = 0

        # Shutdown flag
        self._shutdown = False

    def _get_anthropic_client(self):
        """Get or create the Anthropic client."""
        if self._anthropic_client is None:
            import anthropic

            api_key = get_anthropic_api_key()
            if not api_key:
                raise ValueError(
                    "No Anthropic API key found. Set WINEBOX_ANTHROPIC_API_KEY or "
                    "ANTHROPIC_API_KEY environment variable, or add to secrets.env"
                )
            self._anthropic_client = anthropic.Anthropic(api_key=api_key)
        return self._anthropic_client

    def ensure_indexes(self) -> None:
        """Create indexes on xwines_prices collection.

        Handles migration from old single-field unique index to new
        compound (xwines_id, vintage) unique index.
        """
        from pymongo.errors import OperationFailure

        # Drop old unique index on xwines_id if it conflicts
        try:
            self.prices_col.create_index("xwines_id")
        except OperationFailure as e:
            if e.code == 86:  # IndexKeySpecsConflict
                logger.info("Dropping old unique index on xwines_id")
                try:
                    self.prices_col.drop_index("xwines_id_1")
                except OperationFailure:
                    pass
                self.prices_col.create_index("xwines_id")

        self.prices_col.create_index(
            [("xwines_id", 1), ("vintage", 1)], unique=True
        )
        logger.debug("Ensured indexes on xwines_prices (xwines_id, vintage)")

    @staticmethod
    def parse_vintages(vintages_str: str | None) -> list[int]:
        """Parse the vintages field from xwines_wines into a list of ints.

        The field is stored as a string like "[2020, 2019, 2018]" or
        "['2020', '2019']".

        Args:
            vintages_str: Raw vintages string from the database.

        Returns:
            List of vintage years as ints, or empty list.
        """
        if not vintages_str or not isinstance(vintages_str, str):
            return []
        import ast

        try:
            parsed = ast.literal_eval(vintages_str)
            if isinstance(parsed, list):
                return [int(v) for v in parsed if v]
        except (ValueError, SyntaxError):
            pass
        return []

    def get_remaining_items(self) -> list[tuple[int, int | None]]:
        """Get (xwines_id, vintage) pairs that don't have price documents yet.

        Returns:
            List of (xwines_id, vintage) tuples to process, ordered by priority.
            vintage is int for vintage-specific prices, None for base prices.
        """
        # Get all priced (xwines_id, vintage) pairs
        priced_pairs: set[tuple[int, int | None]] = set()
        for doc in self.prices_col.find({}, {"xwines_id": 1, "vintage": 1}):
            priced_pairs.add((doc["xwines_id"], doc.get("vintage")))

        # Build query for wines
        query: dict[str, Any] = {}
        if self.grape:
            query["$or"] = [
                {"grapes": {"$regex": self.grape, "$options": "i"}},
                {"name": {"$regex": self.grape, "$options": "i"}},
            ]
        if self.min_ratings > 0:
            query["rating_count"] = {"$gte": self.min_ratings}

        # Determine sort order
        if self.priority == "popular":
            sort = [("rating_count", -1)]
        elif self.priority == "alphabetical":
            sort = [("name", 1)]
        else:  # random
            sort = []

        projection = {"xwines_id": 1, "vintages": 1}
        cursor = self.wines_col.find(query, projection)
        if sort:
            cursor = cursor.sort(sort)

        remaining: list[tuple[int, int | None]] = []
        for doc in cursor:
            xid = doc["xwines_id"]
            # Base price (vintage=None)
            if (xid, None) not in priced_pairs:
                remaining.append((xid, None))
            # Per-vintage prices
            vintages = self.parse_vintages(doc.get("vintages"))
            for v in vintages:
                if (xid, v) not in priced_pairs:
                    remaining.append((xid, v))

        if self.priority == "random":
            import random

            random.shuffle(remaining)

        if self.max_wines is not None:
            remaining = remaining[: self.max_wines]

        return remaining

    def get_wines_by_ids(self, xwines_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Fetch wine documents by xwines_id list.

        Returns:
            Dict mapping xwines_id to wine document.
        """
        wines = list(
            self.wines_col.find(
                {"xwines_id": {"$in": xwines_ids}},
                {
                    "xwines_id": 1,
                    "name": 1,
                    "wine_type": 1,
                    "grapes": 1,
                    "abv": 1,
                    "country": 1,
                    "region_name": 1,
                    "winery_name": 1,
                    "avg_rating": 1,
                    "rating_count": 1,
                },
            )
        )
        return {w["xwines_id"]: w for w in wines}

    def build_batch_items(
        self,
        pairs: list[tuple[int, int | None]],
        wine_lookup: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build batch items from (xwines_id, vintage) pairs and wine data.

        Each item is a wine dict augmented with a "vintage" key.

        Args:
            pairs: List of (xwines_id, vintage) tuples.
            wine_lookup: Dict mapping xwines_id to wine document.

        Returns:
            List of item dicts ready for build_batch_prompt().
        """
        items: list[dict[str, Any]] = []
        for xid, vintage in pairs:
            wine = wine_lookup.get(xid)
            if not wine:
                continue
            item = {k: v for k, v in wine.items() if k != "_id"}
            item["vintage"] = vintage
            items.append(item)
        return items

    def lookup_kaggle_price(
        self,
        winery: str,
        wine_name: str,
        vintage: int | None,
    ) -> dict[str, Any] | None:
        """Look up a wine in the kaggle_wine_prices collection.

        Tries exact winery match first, then looks for name overlap.
        Returns the best matching Kaggle price doc or None.

        Args:
            winery: Winery name from X-Wines.
            wine_name: Wine name from X-Wines.
            vintage: Vintage year or None.

        Returns:
            Kaggle price doc dict, or None if no match.
        """
        if not winery:
            return None

        winery_lower = winery.strip().lower()

        # Find Kaggle wines from the same winery
        query: dict[str, Any] = {"winery_lower": winery_lower}
        if vintage is not None:
            # Try exact vintage first
            query["vintage"] = vintage
            match = self.kaggle_col.find_one(query)
            if match:
                return match
            # Fall back to any vintage from same winery
            del query["vintage"]

        candidates = list(self.kaggle_col.find(query).limit(20))
        if not candidates:
            return None

        # Score candidates by name similarity
        name_lower = wine_name.strip().lower()
        name_tokens = set(name_lower.split())

        best: dict[str, Any] | None = None
        best_score = 0.0
        for c in candidates:
            c_name = c.get("name_lower", "")
            c_tokens = set(c_name.split())
            # Token overlap score
            overlap = len(name_tokens & c_tokens)
            if overlap > 0:
                score = overlap / max(len(name_tokens), len(c_tokens))
            elif name_lower in c_name or c_name in name_lower:
                score = 0.3
            else:
                score = 0.0
            # Prefer same vintage
            if vintage and c.get("vintage") == vintage:
                score += 0.5
            if score > best_score:
                best_score = score
                best = c

        # Require minimum name similarity
        return best if best_score >= 0.2 else None

    def lookup_kaggle_context(
        self,
        winery: str | None,
        country: str | None,
        region: str | None,
    ) -> list[dict[str, Any]]:
        """Get Kaggle price context for a wine's winery/region.

        Returns nearby Kaggle prices to use as anchors in the LLM prompt.

        Args:
            winery: Winery name.
            country: Country name.
            region: Region name.

        Returns:
            List of Kaggle price docs (up to 5) as context.
        """
        # Try winery first
        if winery:
            winery_lower = winery.strip().lower()
            docs = list(self.kaggle_col.find(
                {"winery_lower": winery_lower},
                {"name": 1, "price_usd": 1, "vintage": 1, "_id": 0},
            ).limit(3))
            if docs:
                return docs

        # Fall back to region + country
        if country and region:
            docs = list(self.kaggle_col.find(
                {"country": {"$regex": f"^{country}$", "$options": "i"},
                 "region": {"$regex": region, "$options": "i"}},
                {"name": 1, "winery": 1, "price_usd": 1, "vintage": 1, "_id": 0},
            ).limit(5))
            if docs:
                return docs

        # Fall back to country only
        if country:
            docs = list(self.kaggle_col.find(
                {"country": {"$regex": f"^{country}$", "$options": "i"}},
                {"name": 1, "winery": 1, "price_usd": 1, "vintage": 1, "_id": 0},
            ).sort([("rating", -1)]).limit(5))
            return docs

        return []

    def process_kaggle_matches(
        self,
        items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Process items that have direct Kaggle price matches.

        For items with a Kaggle match, writes the price directly without LLM.
        Returns the remaining items that need LLM pricing and the count of
        successfully matched items.

        Args:
            items: All wine-vintage items to process.

        Returns:
            Tuple of (items_needing_llm, kaggle_match_count).
        """
        needs_llm: list[dict[str, Any]] = []
        matched = 0
        now = datetime.now(timezone.utc)

        for item in items:
            winery = item.get("winery_name", "")
            name = item.get("name", "")
            vintage = item.get("vintage")

            kaggle = self.lookup_kaggle_price(winery, name, vintage)
            if kaggle and kaggle.get("price_usd"):
                price = kaggle["price_usd"]
                # Build a price range: ±15% of the Kaggle price
                price_low = round(price * 0.85, 2)
                price_high = round(price * 1.15, 2)

                # Determine tier
                midpoint = price
                price_tier = "mid_range"
                for tier, (lo, hi) in PRICE_TIERS.items():
                    if lo <= midpoint < hi:
                        price_tier = tier
                        break

                doc = {
                    "xwines_id": item["xwines_id"],
                    "vintage": vintage,
                    "price_low_usd": price_low,
                    "price_high_usd": price_high,
                    "price_tier": price_tier,
                    "confidence": "high",
                    "note": f"Based on Vivino market price ${price:.2f}",
                    "model": "kaggle-vivino",
                    "created_at": now,
                }

                try:
                    self.prices_col.update_one(
                        {"xwines_id": item["xwines_id"], "vintage": vintage},
                        {"$set": doc},
                        upsert=True,
                    )
                    matched += 1
                except Exception as e:
                    logger.warning(
                        "Failed to insert Kaggle price for wine %d: %s",
                        item["xwines_id"], e,
                    )
                    needs_llm.append(item)
            else:
                # Add Kaggle context for the LLM prompt
                context = self.lookup_kaggle_context(
                    winery, item.get("country"), item.get("region_name"),
                )
                if context:
                    item["_kaggle_context"] = context
                needs_llm.append(item)

        return needs_llm, matched

    def process_batch(self, items: list[dict[str, Any]]) -> int:
        """Process a single batch of wine-vintage items through the API.

        Args:
            items: List of wine-vintage dicts (wine data + "vintage" key).

        Returns:
            Number of successfully priced items.
        """
        if self._shutdown:
            return 0

        prompt = build_batch_prompt(items)

        if self.verbose:
            logger.debug("Batch prompt (%d items):\n%s", len(items), prompt)

        # Call Claude API with retries
        response_text = self._call_api_with_retries(prompt)
        if response_text is None:
            with self._lock:
                self.failed += len(items)
            return 0

        # Parse response
        entries = parse_response(response_text)
        if entries is None:
            logger.warning(
                "Failed to parse JSON response for batch of %d items. "
                "Raw response: %s",
                len(items),
                response_text[:500],
            )
            with self._lock:
                self.failed += len(items)
            return 0

        if len(entries) != len(items):
            logger.warning(
                "Response has %d entries but batch had %d items — "
                "processing available entries",
                len(entries),
                len(items),
            )

        # Validate and insert each entry
        success_count = 0
        now = datetime.now(timezone.utc)

        for idx, (item, entry) in enumerate(zip(items, entries)):
            validated = validate_price_entry(entry)
            if validated is None:
                logger.warning(
                    "Invalid price entry for wine %d vintage %s (%s): %s",
                    item["xwines_id"],
                    item.get("vintage"),
                    item.get("name", "?"),
                    entry,
                )
                with self._lock:
                    self.failed += 1
                continue

            doc = {
                "xwines_id": item["xwines_id"],
                "vintage": item.get("vintage"),
                **validated,
                "model": self.model,
                "created_at": now,
            }

            try:
                self.prices_col.update_one(
                    {
                        "xwines_id": item["xwines_id"],
                        "vintage": item.get("vintage"),
                    },
                    {"$set": doc},
                    upsert=True,
                )
                success_count += 1
                with self._lock:
                    self.succeeded += 1
            except Exception as e:
                logger.warning(
                    "Failed to insert price for wine %d vintage %s: %s",
                    item["xwines_id"],
                    item.get("vintage"),
                    e,
                )
                with self._lock:
                    self.failed += 1

        # Count items that didn't get entries (response was too short)
        unmatched = len(items) - len(entries)
        if unmatched > 0:
            with self._lock:
                self.failed += unmatched

        with self._lock:
            self.processed += len(items)
        return success_count

    def _call_api_with_retries(
        self,
        prompt: str,
        max_retries: int = 5,
    ) -> str | None:
        """Call the Anthropic API with exponential backoff on errors.

        Args:
            prompt: The user prompt to send.
            max_retries: Maximum retry attempts.

        Returns:
            Response text, or None on total failure.
        """
        import anthropic

        client = self._get_anthropic_client()
        base_delay = 30.0

        for attempt in range(max_retries + 1):
            if self._shutdown:
                return None

            try:
                # Rate limit: ensure minimum interval between requests
                with self._rate_lock:
                    now = time.monotonic()
                    elapsed = now - self._last_request_time
                    if elapsed < self._min_request_interval:
                        time.sleep(self._min_request_interval - elapsed)
                    self._last_request_time = time.monotonic()

                message = client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                return message.content[0].text

            except anthropic.RateLimitError as e:
                if attempt == max_retries:
                    logger.error("Rate limit exceeded after %d retries: %s", max_retries, e)
                    return None
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d), waiting %.0fs...",
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)

            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    if attempt == max_retries:
                        logger.error("API server error after %d retries: %s", max_retries, e)
                        return None
                    delay = 5.0 * (2**attempt)
                    logger.warning(
                        "API server error %d (attempt %d/%d), waiting %.0fs...",
                        e.status_code,
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error("API client error %d: %s", e.status_code, e)
                    return None

            except Exception as e:
                logger.error("Unexpected API error: %s", e)
                return None

        return None

    def run(self) -> None:
        """Run the annotation process."""
        self.ensure_indexes()

        remaining_pairs = self.get_remaining_items()
        total_remaining = len(remaining_pairs)

        if total_remaining == 0:
            print("All wine-vintage pairs already priced. Nothing to do.")
            return

        total_batches = (total_remaining + self.batch_size - 1) // self.batch_size

        # Count unique wines
        unique_wines = len({xid for xid, _ in remaining_pairs})

        print(f"\nX-Wines Vintage Price Annotation")
        print("=" * 50)
        print(f"Database: {self.db_name}")
        print(f"Model: {self.model}")
        print(f"Wine-vintage pairs to process: {total_remaining:,}")
        print(f"Unique wines: {unique_wines:,}")
        print(f"Batch size: {self.batch_size}")
        print(f"Total batches: {total_batches:,}")
        print(f"Concurrency: {self.concurrency} threads")
        print(f"Priority: {self.priority}")
        if self.grape:
            print(f"Grape filter: {self.grape}")
        if self.min_ratings > 0:
            print(f"Min ratings filter: {self.min_ratings}")
        print()

        # Check Kaggle data availability
        kaggle_count = self.kaggle_col.count_documents({})
        if kaggle_count > 0:
            print(f"Kaggle price data: {kaggle_count:,} reference wines available")
        else:
            print("Kaggle price data: none (run import_kaggle_prices.py first for better accuracy)")
        print()

        if self.dry_run:
            print("[DRY RUN] Would process the above. No API calls made.")
            return

        # Collect all unique wine IDs and fetch their data
        all_wine_ids = list({xid for xid, _ in remaining_pairs})
        wine_lookup = self.get_wines_by_ids(all_wine_ids)

        # Build all items
        all_items = self.build_batch_items(remaining_pairs, wine_lookup)

        # Phase 1: Direct Kaggle price matches (no LLM needed)
        if kaggle_count > 0:
            print("Phase 1: Matching against Kaggle/Vivino prices...")
            needs_llm, kaggle_matched = self.process_kaggle_matches(all_items)
            self.kaggle_matched = kaggle_matched
            with self._lock:
                self.succeeded += kaggle_matched
                self.processed += kaggle_matched
            print(f"  Kaggle direct matches: {kaggle_matched:,}")
            print(f"  Remaining for LLM: {len(needs_llm):,}")
            print()
        else:
            needs_llm = all_items

        if not needs_llm:
            print("All items matched via Kaggle. No LLM calls needed.")
            self._print_summary()
            return

        # Phase 2: LLM pricing for remaining items (with Kaggle context where available)
        total_llm = len(needs_llm)
        print(f"Phase 2: LLM pricing for {total_llm:,} items...")

        # Build batches from remaining items
        batches: list[list[dict[str, Any]]] = []
        for i in range(0, total_llm, self.batch_size):
            batch = needs_llm[i : i + self.batch_size]
            if batch:
                batches.append(batch)

        # Process with thread pool
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = {
                executor.submit(self.process_batch, batch): idx
                for idx, batch in enumerate(batches)
            }

            for future in as_completed(futures):
                if self._shutdown:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    future.result()
                except Exception as e:
                    logger.error("Batch failed with exception: %s", e)

                # Progress update (LLM phase only)
                llm_processed = self.processed - self.kaggle_matched
                pct = (llm_processed / total_llm) * 100 if total_llm else 100
                print(
                    f"\rLLM Progress: {llm_processed:,}/{total_llm:,} "
                    f"({pct:.1f}%) | "
                    f"OK: {self.succeeded:,} | "
                    f"Failed: {self.failed:,} | "
                    f"Kaggle: {self.kaggle_matched:,}",
                    end="",
                    flush=True,
                )

        print()  # Newline after progress
        self._print_summary()

    def _print_summary(self) -> None:
        """Print final summary of the annotation run."""
        print(f"\nAnnotation complete!")
        print(f"  Processed: {self.processed:,}")
        print(f"  Kaggle matched: {self.kaggle_matched:,}")
        print(f"  LLM priced: {self.succeeded - self.kaggle_matched:,}")
        print(f"  Succeeded: {self.succeeded:,}")
        print(f"  Failed: {self.failed:,}")
        total_priced = self.prices_col.count_documents({})
        base_priced = self.prices_col.count_documents({"vintage": None})
        vintage_priced = total_priced - base_priced
        kaggle_sourced = self.prices_col.count_documents({"model": "kaggle-vivino"})
        total_wines = self.wines_col.count_documents({})
        print(f"  Total price docs: {total_priced:,}")
        print(f"  Base prices: {base_priced:,}/{total_wines:,} wines")
        print(f"  Vintage prices: {vintage_priced:,}")
        print(f"  Kaggle-sourced: {kaggle_sourced:,}")

    def show_status(self) -> None:
        """Show current progress and exit."""
        total_wines = self.wines_col.count_documents({})
        total_priced = self.prices_col.count_documents({})
        base_priced = self.prices_col.count_documents({"vintage": None})
        vintage_priced = total_priced - base_priced
        wines_with_base = base_priced  # 1:1 with wines

        print(f"\nX-Wines Vintage Price Annotation Status")
        print("=" * 50)
        print(f"Database: {self.db_name}")
        print(f"Total wines: {total_wines:,}")
        print(f"Wines with base price: {wines_with_base:,}")
        print(f"Vintage-specific prices: {vintage_priced:,}")
        print(f"Total price documents: {total_priced:,}")
        if total_wines > 0:
            pct = (wines_with_base / total_wines) * 100
            print(f"Base price coverage: {pct:.1f}%")

        # Show tier breakdown
        if total_priced > 0:
            print(f"\nPrice tier breakdown:")
            pipeline = [
                {"$group": {"_id": "$price_tier", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
            for doc in self.prices_col.aggregate(pipeline):
                tier = doc["_id"] or "unknown"
                count = doc["count"]
                print(f"  {tier}: {count:,}")

            # Show confidence breakdown
            print(f"\nConfidence breakdown:")
            pipeline = [
                {"$group": {"_id": "$confidence", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
            for doc in self.prices_col.aggregate(pipeline):
                confidence = doc["_id"] or "unknown"
                count = doc["count"]
                print(f"  {confidence}: {count:,}")

    def estimate_cost(self) -> None:
        """Estimate remaining API cost and exit."""
        remaining_pairs = self.get_remaining_items()
        remaining = len(remaining_pairs)

        if remaining == 0:
            print("All wine-vintage pairs already priced. No cost remaining.")
            return

        unique_wines = len({xid for xid, _ in remaining_pairs})
        batches = (remaining + self.batch_size - 1) // self.batch_size

        # Haiku pricing: $0.80/M input, $4/M output tokens
        # Estimate ~150 input tokens per item (wine + vintage), ~50 output tokens
        input_tokens_per_batch = 200 + (150 * self.batch_size)  # system + items
        output_tokens_per_batch = 50 * self.batch_size

        total_input = batches * input_tokens_per_batch
        total_output = batches * output_tokens_per_batch

        input_cost = (total_input / 1_000_000) * 0.80
        output_cost = (total_output / 1_000_000) * 4.00
        total_cost = input_cost + output_cost

        print(f"\nX-Wines Vintage Price Annotation Cost Estimate")
        print("=" * 50)
        print(f"Model: {self.model}")
        print(f"Remaining wine-vintage pairs: {remaining:,}")
        print(f"Unique wines: {unique_wines:,}")
        print(f"Batch size: {self.batch_size}")
        print(f"Batches needed: {batches:,}")
        print(f"\nEstimated tokens:")
        print(f"  Input:  {total_input:,.0f}")
        print(f"  Output: {total_output:,.0f}")
        print(f"\nEstimated cost:")
        print(f"  Input:  ${input_cost:.2f}")
        print(f"  Output: ${output_cost:.2f}")
        print(f"  Total:  ${total_cost:.2f}")

    def reset(self) -> None:
        """Delete all price data."""
        count = self.prices_col.count_documents({})
        if count == 0:
            print("No price data to delete.")
            return

        print(f"Deleting {count:,} price documents from xwines_prices...")
        self.prices_col.drop()
        print("Done. Collection dropped.")

    def shutdown(self) -> None:
        """Signal graceful shutdown."""
        self._shutdown = True

    def close(self) -> None:
        """Close MongoDB connection."""
        self.client.close()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Annotate X-Wines dataset with estimated retail prices using Claude",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Wines per API call (default: 20)",
    )
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Claude model to use (default: claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--max-wines",
        type=int,
        default=None,
        help="Limit total wines to process",
    )
    parser.add_argument(
        "--min-ratings",
        type=int,
        default=0,
        help="Only wines with >= N ratings (default: 0)",
    )
    parser.add_argument(
        "--grape",
        default=None,
        help="Filter by grape variety (e.g., 'Pinot Noir')",
    )
    parser.add_argument(
        "--priority",
        choices=["popular", "alphabetical", "random"],
        default="popular",
        help='Processing order (default: popular)',
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Concurrent API requests (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without calling API",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show progress and exit",
    )
    parser.add_argument(
        "--estimate-cost",
        action="store_true",
        help="Estimate remaining API cost and exit",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all price data and start fresh",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Override MongoDB database name",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    annotator = PriceAnnotator(
        batch_size=args.batch_size,
        model=args.model,
        max_wines=args.max_wines,
        min_ratings=args.min_ratings,
        grape=args.grape,
        priority=args.priority,
        concurrency=args.concurrency,
        dry_run=args.dry_run,
        database=args.database,
        verbose=args.verbose,
    )

    # Handle Ctrl+C gracefully
    def signal_handler(signum: int, frame: Any) -> None:
        print("\n\nShutting down gracefully (finishing current batch)...")
        annotator.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if args.status:
            annotator.show_status()
            return 0

        if args.estimate_cost:
            annotator.estimate_cost()
            return 0

        if args.reset:
            annotator.reset()
            return 0

        # Run the annotation
        annotator.run()
        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        return 130
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=args.verbose)
        return 1
    finally:
        annotator.close()


if __name__ == "__main__":
    sys.exit(main())
