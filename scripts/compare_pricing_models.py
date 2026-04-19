#!/usr/bin/env python3
"""Compare Haiku vs Sonnet pricing accuracy against web-validated prices.

Takes wines from xwines_price_validations that have web prices,
re-prices them with Sonnet, and compares both models' accuracy.

Usage:
    uv run python scripts/compare_pricing_models.py
    uv run python scripts/compare_pricing_models.py --max-wines 20
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from scripts.annotate_xwines_prices import (
    SYSTEM_PROMPT,
    build_batch_prompt,
    get_anthropic_api_key,
    get_mongodb_url,
    parse_response,
    validate_price_entry,
)

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Haiku vs Sonnet pricing accuracy",
    )
    parser.add_argument(
        "--max-wines", type=int, default=None,
        help="Limit wines to compare (default: all validated with web prices)",
    )
    parser.add_argument(
        "--database", default=None,
        help="Override MongoDB database name",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Setup
    mongo_url = get_mongodb_url()
    db_name = args.database or os.environ.get("WINEBOX_DATABASE", "winebox_oat")
    client: MongoClient = MongoClient(mongo_url)
    db = client[db_name]

    api_key = get_anthropic_api_key()
    if not api_key:
        print("Error: No Anthropic API key found.")
        return 1

    import anthropic
    anthropic_client = anthropic.Anthropic(api_key=api_key)

    # Get validated wines that have web prices
    query: dict[str, Any] = {"search_price": {"$ne": None}, "status": {"$ne": "no_data"}}
    validations = list(db["xwines_price_validations"].find(query))

    if not validations:
        print("No validated wines with web prices found. Run validate_xwines_prices.py first.")
        return 1

    if args.max_wines:
        validations = validations[:args.max_wines]

    print(f"\nHaiku vs Sonnet Pricing Comparison")
    print("=" * 60)
    print(f"Database: {db_name}")
    print(f"Wines to compare: {len(validations)}")
    print()

    # Build items for Sonnet pricing (batch of all wines)
    items: list[dict[str, Any]] = []
    for v in validations:
        wine = db["xwines_wines"].find_one(
            {"xwines_id": v["xwines_id"]},
            {
                "xwines_id": 1, "name": 1, "wine_type": 1, "grapes": 1,
                "abv": 1, "country": 1, "region_name": 1, "winery_name": 1,
                "avg_rating": 1, "rating_count": 1,
            },
        )
        if not wine:
            continue
        item = {k: val for k, val in wine.items() if k != "_id"}
        item["vintage"] = v.get("vintage")
        items.append(item)

    # Process in batches of 10 (Sonnet is more expensive, smaller batches)
    batch_size = 10
    sonnet_results: list[dict[str, Any] | None] = []

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        prompt = build_batch_prompt(batch)

        print(f"\rPricing batch {i // batch_size + 1}/{(len(items) + batch_size - 1) // batch_size} with Sonnet...", end="", flush=True)

        try:
            time.sleep(1.0)  # Rate limit
            message = anthropic_client.messages.create(
                model="claude-4-sonnet-20250514",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = message.content[0].text
            entries = parse_response(response_text)

            if entries and len(entries) == len(batch):
                for entry in entries:
                    validated = validate_price_entry(entry)
                    sonnet_results.append(validated)
            else:
                logger.warning("Sonnet batch returned %d entries for %d items",
                             len(entries) if entries else 0, len(batch))
                sonnet_results.extend([None] * len(batch))
        except Exception as e:
            logger.error("Sonnet API call failed: %s", e)
            sonnet_results.extend([None] * len(batch))

    print()
    print()

    # Compare results
    haiku_accurate = 0
    haiku_close = 0
    haiku_over = 0
    haiku_under = 0
    sonnet_accurate = 0
    sonnet_close = 0
    sonnet_over = 0
    sonnet_under = 0
    compared = 0

    print(f"{'Wine':<40} {'Web $':>8} {'Haiku':>14} {'Sonnet':>14} {'H?':>4} {'S?':>4}")
    print("-" * 88)

    for v, sonnet in zip(validations, sonnet_results):
        web_price = v.get("search_price")
        if not web_price or not sonnet:
            continue

        compared += 1
        h_low = v.get("estimated_low", 0)
        h_high = v.get("estimated_high", 0)
        s_low = sonnet.get("price_low_usd", 0)
        s_high = sonnet.get("price_high_usd", 0)

        # Haiku accuracy
        h_status = _classify(h_low, h_high, web_price)
        if h_status == "accurate":
            haiku_accurate += 1
        elif h_status == "close":
            haiku_close += 1
        elif h_status == "over":
            haiku_over += 1
        else:
            haiku_under += 1

        # Sonnet accuracy
        s_status = _classify(s_low, s_high, web_price)
        if s_status == "accurate":
            sonnet_accurate += 1
        elif s_status == "close":
            sonnet_close += 1
        elif s_status == "over":
            sonnet_over += 1
        else:
            sonnet_under += 1

        wine_name = v.get("wine_name", "?")[:38]
        h_label = _status_icon(h_status)
        s_label = _status_icon(s_status)

        print(f"{wine_name:<40} ${web_price:>6.0f}  ${h_low:.0f}-${h_high:.0f}  ${s_low:.0f}-${s_high:.0f}  {h_label:>4} {s_label:>4}")

    print()
    print(f"Compared: {compared} wines")
    print()
    print(f"{'':30} {'Haiku':>12} {'Sonnet':>12}")
    print(f"{'-'*56}")

    if compared > 0:
        h_good = haiku_accurate + haiku_close
        s_good = sonnet_accurate + sonnet_close
        print(f"{'Accurate (in range)':<30} {haiku_accurate:>8} ({haiku_accurate/compared*100:.0f}%)  {sonnet_accurate:>4} ({sonnet_accurate/compared*100:.0f}%)")
        print(f"{'Close (<30% off)':<30} {haiku_close:>8} ({haiku_close/compared*100:.0f}%)  {sonnet_close:>4} ({sonnet_close/compared*100:.0f}%)")
        print(f"{'Overestimated (>30%)':<30} {haiku_over:>8} ({haiku_over/compared*100:.0f}%)  {sonnet_over:>4} ({sonnet_over/compared*100:.0f}%)")
        print(f"{'Underestimated (>30%)':<30} {haiku_under:>8} ({haiku_under/compared*100:.0f}%)  {sonnet_under:>4} ({sonnet_under/compared*100:.0f}%)")
        print(f"{'-'*56}")
        print(f"{'Acceptable (accurate+close)':<30} {h_good:>8} ({h_good/compared*100:.0f}%)  {s_good:>4} ({s_good/compared*100:.0f}%)")

    client.close()
    return 0


def _classify(est_low: float, est_high: float, actual: float) -> str:
    """Classify estimate accuracy."""
    if est_low <= actual <= est_high:
        return "accurate"
    if actual < est_low:
        pct = ((est_low - actual) / actual) * 100
        return "over" if pct > 30 else "close"
    else:
        pct = ((actual - est_high) / actual) * 100
        return "under" if pct > 30 else "close"


def _status_icon(status: str) -> str:
    """Return a short label for the status."""
    return {
        "accurate": "OK",
        "close": "~OK",
        "over": "HIGH",
        "under": "LOW",
    }.get(status, "?")


if __name__ == "__main__":
    sys.exit(main())
