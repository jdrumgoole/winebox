#!/usr/bin/env python3
"""Annotate X-Wines dataset with estimated retail prices using Claude.

Standalone script that uses the Anthropic API (Claude Haiku) to estimate
retail prices for wines in the xwines_wines collection. Results are stored
in a separate xwines_prices collection to keep reference data clean.

Uses pymongo directly (not Beanie) following the pattern of
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
region, grape variety, and other attributes.

Guidelines:
- Prices should reflect current US retail market (wine shop / online retailer)
- Consider the producer's reputation, region prestige, and classification
- For unknown or obscure wines, use regional averages as a baseline
- Be conservative with confidence ratings — use "high" only for well-known wines
- price_tier definitions: budget (<$15), value ($15-25), mid_range ($25-50), \
premium ($50-100), luxury ($100-250), ultra_premium (>$250)"""


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


def build_batch_prompt(wines: list[dict[str, Any]]) -> str:
    """Build the user prompt for a batch of wines.

    Args:
        wines: List of wine documents from xwines_wines collection.

    Returns:
        Formatted prompt string.
    """
    lines = [
        "Estimate retail prices for these wines. For each, provide:",
        '- price_low / price_high (USD, numbers only)',
        '- confidence: "high" | "medium" | "low"',
        '- price_tier: "budget" (<$15) | "value" ($15-25) | "mid_range" ($25-50) '
        '| "premium" ($50-100) | "luxury" ($100-250) | "ultra_premium" (>$250)',
        "- note: 1-sentence justification",
        "",
        "Return ONLY a JSON array, one object per wine, same order as listed.",
        "Each object: {\"price_low\": N, \"price_high\": N, \"confidence\": \"...\", "
        "\"price_tier\": \"...\", \"note\": \"...\"}",
        "",
        "Wines:",
    ]

    for i, wine in enumerate(wines, 1):
        parts = [wine.get("name", "Unknown")]

        winery = wine.get("winery_name")
        if winery:
            parts.append(f"| {winery}")

        wine_type = wine.get("wine_type")
        if wine_type:
            parts.append(f"| {wine_type}")

        region = wine.get("region_name")
        country = wine.get("country")
        location = ", ".join(filter(None, [region, country]))
        if location:
            parts.append(f"| {location}")

        grapes = wine.get("grapes")
        if grapes:
            parts.append(f"| {grapes}")

        abv = wine.get("abv")
        if abv:
            parts.append(f"| {abv}%")

        avg_rating = wine.get("avg_rating")
        rating_count = wine.get("rating_count", 0)
        if avg_rating is not None:
            parts.append(f"| Rating: {avg_rating} ({rating_count})")

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
        price_high = float(entry.get("price_high", 0))
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
        self.db_name = database or os.environ.get("WINEBOX_DATABASE", "winebox-oat")
        self.client: MongoClient = MongoClient(self.mongo_url)
        self.db = self.client[self.db_name]
        self.wines_col = self.db["xwines_wines"]
        self.prices_col = self.db["xwines_prices"]

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
        """Create indexes on xwines_prices collection."""
        self.prices_col.create_index("xwines_id", unique=True)
        logger.debug("Ensured unique index on xwines_prices.xwines_id")

    def get_remaining_wine_ids(self) -> list[int]:
        """Get xwines_ids that don't have price documents yet.

        Returns:
            List of xwines_id values to process, ordered by priority.
        """
        # Get all priced wine IDs
        priced_ids = set(
            doc["xwines_id"] for doc in self.prices_col.find({}, {"xwines_id": 1})
        )

        # Build query for unpriced wines
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
        else:  # random — fetch all and shuffle
            sort = []

        projection = {"xwines_id": 1}
        cursor = self.wines_col.find(query, projection)
        if sort:
            cursor = cursor.sort(sort)

        remaining = []
        for doc in cursor:
            xid = doc["xwines_id"]
            if xid not in priced_ids:
                remaining.append(xid)

        if self.priority == "random":
            import random

            random.shuffle(remaining)

        if self.max_wines is not None:
            remaining = remaining[: self.max_wines]

        return remaining

    def get_wines_by_ids(self, xwines_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch wine documents by xwines_id list."""
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
        # Maintain requested order
        id_to_wine = {w["xwines_id"]: w for w in wines}
        return [id_to_wine[xid] for xid in xwines_ids if xid in id_to_wine]

    def process_batch(self, wines: list[dict[str, Any]]) -> int:
        """Process a single batch of wines through the API.

        Args:
            wines: List of wine documents to price.

        Returns:
            Number of successfully priced wines.
        """
        if self._shutdown:
            return 0

        prompt = build_batch_prompt(wines)

        if self.verbose:
            logger.debug("Batch prompt (%d wines):\n%s", len(wines), prompt)

        # Call Claude API with retries
        response_text = self._call_api_with_retries(prompt)
        if response_text is None:
            with self._lock:
                self.failed += len(wines)
            return 0

        # Parse response
        entries = parse_response(response_text)
        if entries is None:
            logger.warning(
                "Failed to parse JSON response for batch of %d wines. "
                "Raw response: %s",
                len(wines),
                response_text[:500],
            )
            with self._lock:
                self.failed += len(wines)
            return 0

        if len(entries) != len(wines):
            logger.warning(
                "Response has %d entries but batch had %d wines — "
                "processing available entries",
                len(entries),
                len(wines),
            )

        # Validate and insert each entry
        success_count = 0
        now = datetime.now(timezone.utc)

        for idx, (wine, entry) in enumerate(zip(wines, entries)):
            validated = validate_price_entry(entry)
            if validated is None:
                logger.warning(
                    "Invalid price entry for wine %d (%s): %s",
                    wine["xwines_id"],
                    wine.get("name", "?"),
                    entry,
                )
                with self._lock:
                    self.failed += 1
                continue

            doc = {
                "xwines_id": wine["xwines_id"],
                **validated,
                "model": self.model,
                "created_at": now,
            }

            try:
                self.prices_col.update_one(
                    {"xwines_id": wine["xwines_id"]},
                    {"$set": doc},
                    upsert=True,
                )
                success_count += 1
                with self._lock:
                    self.succeeded += 1
            except Exception as e:
                logger.warning(
                    "Failed to insert price for wine %d: %s",
                    wine["xwines_id"],
                    e,
                )
                with self._lock:
                    self.failed += 1

        # Count wines that didn't get entries (response was too short)
        unmatched = len(wines) - len(entries)
        if unmatched > 0:
            with self._lock:
                self.failed += unmatched

        with self._lock:
            self.processed += len(wines)
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

        remaining_ids = self.get_remaining_wine_ids()
        total_remaining = len(remaining_ids)

        if total_remaining == 0:
            print("All wines already priced. Nothing to do.")
            return

        total_batches = (total_remaining + self.batch_size - 1) // self.batch_size

        print(f"\nX-Wines Price Annotation")
        print("=" * 50)
        print(f"Database: {self.db_name}")
        print(f"Model: {self.model}")
        print(f"Wines to process: {total_remaining:,}")
        print(f"Batch size: {self.batch_size}")
        print(f"Total batches: {total_batches:,}")
        print(f"Concurrency: {self.concurrency} threads")
        print(f"Priority: {self.priority}")
        if self.grape:
            print(f"Grape filter: {self.grape}")
        if self.min_ratings > 0:
            print(f"Min ratings filter: {self.min_ratings}")
        print()

        if self.dry_run:
            print("[DRY RUN] Would process the above. No API calls made.")
            return

        # Build all batches upfront
        batches: list[list[dict[str, Any]]] = []
        for i in range(0, total_remaining, self.batch_size):
            batch_ids = remaining_ids[i : i + self.batch_size]
            wines = self.get_wines_by_ids(batch_ids)
            if wines:
                batches.append(wines)

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

                # Progress update
                pct = (self.processed / total_remaining) * 100
                print(
                    f"\rProgress: {self.processed:,}/{total_remaining:,} "
                    f"({pct:.1f}%) | "
                    f"OK: {self.succeeded:,} | "
                    f"Failed: {self.failed:,}",
                    end="",
                    flush=True,
                )

        print()  # Newline after progress
        self._print_summary()

    def _print_summary(self) -> None:
        """Print final summary of the annotation run."""
        print(f"\nAnnotation complete!")
        print(f"  Processed: {self.processed:,}")
        print(f"  Succeeded: {self.succeeded:,}")
        print(f"  Failed: {self.failed:,}")
        total_priced = self.prices_col.count_documents({})
        total_wines = self.wines_col.count_documents({})
        print(f"  Total priced: {total_priced:,}/{total_wines:,}")

    def show_status(self) -> None:
        """Show current progress and exit."""
        total_wines = self.wines_col.count_documents({})
        total_priced = self.prices_col.count_documents({})
        remaining = total_wines - total_priced

        print(f"\nX-Wines Price Annotation Status")
        print("=" * 50)
        print(f"Database: {self.db_name}")
        print(f"Total wines: {total_wines:,}")
        print(f"Priced: {total_priced:,}")
        print(f"Remaining: {remaining:,}")
        if total_wines > 0:
            pct = (total_priced / total_wines) * 100
            print(f"Progress: {pct:.1f}%")

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
        remaining_ids = self.get_remaining_wine_ids()
        remaining = len(remaining_ids)

        if remaining == 0:
            print("All wines already priced. No cost remaining.")
            return

        batches = (remaining + self.batch_size - 1) // self.batch_size

        # Haiku pricing: $0.80/M input, $4/M output tokens
        # Estimate ~140 input tokens per wine, ~50 output tokens per wine
        input_tokens_per_batch = 200 + (140 * self.batch_size)  # system + wines
        output_tokens_per_batch = 50 * self.batch_size

        total_input = batches * input_tokens_per_batch
        total_output = batches * output_tokens_per_batch

        input_cost = (total_input / 1_000_000) * 0.80
        output_cost = (total_output / 1_000_000) * 4.00
        total_cost = input_cost + output_cost

        print(f"\nX-Wines Price Annotation Cost Estimate")
        print("=" * 50)
        print(f"Model: {self.model}")
        print(f"Remaining wines: {remaining:,}")
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
