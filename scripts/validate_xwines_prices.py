#!/usr/bin/env python3
"""Validate X-Wines price estimates by spot-checking against Wine-Searcher.

Samples price documents from xwines_prices, searches Wine-Searcher for each
wine (via web search), and compares the estimated price range to the actual
market price. Produces a report showing accuracy, outliers, and overall
confidence in the dataset.

Usage:
    uv run python scripts/validate_xwines_prices.py [OPTIONS]

Examples:
    uv run python scripts/validate_xwines_prices.py --sample-size 50
    uv run python scripts/validate_xwines_prices.py --sample-size 100 --tier premium
    uv run python scripts/validate_xwines_prices.py --report
"""

import argparse
import json
import logging
import os
import re
import signal
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient

logger = logging.getLogger(__name__)


def get_mongodb_url() -> str:
    """Get MongoDB connection URL from environment or secrets.env."""
    url = os.environ.get("WINEBOX_MONGODB_URL")
    if url:
        return url

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


def get_brave_api_key() -> str | None:
    """Get Brave Search API key from environment or secrets.env."""
    key = os.environ.get("BRAVE_API_KEY")
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
                if line.startswith("BRAVE_API_KEY="):
                    value = line.split("=", 1)[1].strip()
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    return value

    return None


def search_wine_price(
    wine_name: str,
    vintage: int | None,
    brave_api_key: str,
) -> dict[str, Any] | None:
    """Search for a wine's retail price using Brave Search API.

    Searches for the wine name + vintage + "price USD" and extracts
    price information from the search results.

    Args:
        wine_name: Name of the wine (including winery).
        vintage: Vintage year, or None for base price.
        brave_api_key: Brave Search API key.

    Returns:
        Dict with search_price, source, and raw_snippet, or None if not found.
    """
    import urllib.request

    query_parts = [wine_name]
    if vintage:
        query_parts.append(str(vintage))
    query_parts.append("wine price USD buy")
    query = " ".join(query_parts)

    encoded_query = urllib.parse.quote(query)
    url = f"https://api.search.brave.com/res/v1/web/search?q={encoded_query}&count=5"

    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("Accept-Encoding", "gzip")
    req.add_header("X-Subscription-Token", brave_api_key)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import gzip
            import io

            if resp.headers.get("Content-Encoding") == "gzip":
                data = gzip.GzipFile(fileobj=io.BytesIO(resp.read())).read()
            else:
                data = resp.read()
            results = json.loads(data.decode("utf-8"))
    except Exception as e:
        logger.debug("Brave Search failed for '%s': %s", query, e)
        return None

    # Extract prices from search results
    web_results = results.get("web", {}).get("results", [])
    if not web_results:
        return None

    prices_found: list[dict[str, Any]] = []

    for result in web_results:
        title = result.get("title", "")
        description = result.get("description", "")
        result_url = result.get("url", "")
        text = f"{title} {description}"

        # Extract dollar amounts from the text
        price_matches = re.findall(r"\$(\d{1,5}(?:\.\d{2})?)", text)
        for price_str in price_matches:
            try:
                price = float(price_str)
                # Reasonable wine price range
                if 3.0 <= price <= 50000.0:
                    source = "unknown"
                    if "wine-searcher" in result_url.lower():
                        source = "wine-searcher"
                    elif "wine.com" in result_url.lower():
                        source = "wine.com"
                    elif "totalwine" in result_url.lower():
                        source = "totalwine"
                    elif "vivino" in result_url.lower():
                        source = "vivino"

                    prices_found.append({
                        "price": price,
                        "source": source,
                        "snippet": text[:200],
                        "url": result_url,
                    })
            except ValueError:
                continue

    if not prices_found:
        return None

    # Prefer known wine retailer sources
    preferred_sources = ["wine-searcher", "wine.com", "totalwine", "vivino"]
    for source in preferred_sources:
        for p in prices_found:
            if p["source"] == source:
                return {
                    "search_price": p["price"],
                    "source": p["source"],
                    "snippet": p["snippet"],
                    "url": p["url"],
                }

    # Fall back to first price found
    return {
        "search_price": prices_found[0]["price"],
        "source": prices_found[0]["source"],
        "snippet": prices_found[0]["snippet"],
        "url": prices_found[0]["url"],
    }


class PriceValidator:
    """Validates X-Wines price estimates against web search results."""

    def __init__(
        self,
        *,
        sample_size: int = 50,
        tier: str | None = None,
        database: str | None = None,
        verbose: bool = False,
    ) -> None:
        self.sample_size = sample_size
        self.tier = tier
        self.verbose = verbose

        self.mongo_url = get_mongodb_url()
        self.db_name = database or os.environ.get("WINEBOX_DATABASE", "winebox_oat")
        self.client: MongoClient = MongoClient(self.mongo_url)
        self.db = self.client[self.db_name]
        self.prices_col = self.db["xwines_prices"]
        self.wines_col = self.db["xwines_wines"]
        self.validations_col = self.db["xwines_price_validations"]

        self.brave_api_key = get_brave_api_key()
        self._shutdown = False

    def sample_prices(self) -> list[dict[str, Any]]:
        """Sample price documents for validation.

        Returns a random sample, optionally filtered by tier.
        Prefers vintage-specific prices but includes base prices too.
        """
        match_stage: dict[str, Any] = {}
        if self.tier:
            match_stage["price_tier"] = self.tier

        pipeline: list[dict] = []
        if match_stage:
            pipeline.append({"$match": match_stage})
        pipeline.append({"$sample": {"size": self.sample_size}})

        return list(self.prices_col.aggregate(pipeline))

    def validate_sample(self, price_doc: dict[str, Any]) -> dict[str, Any] | None:
        """Validate a single price document against web search.

        Args:
            price_doc: Document from xwines_prices.

        Returns:
            Validation result dict, or None if search failed.
        """
        if self._shutdown:
            return None

        xwines_id = price_doc["xwines_id"]
        vintage = price_doc.get("vintage")

        # Look up wine name
        wine = self.wines_col.find_one(
            {"xwines_id": xwines_id},
            {"name": 1, "winery_name": 1},
        )
        if not wine:
            return None

        wine_name = wine.get("name", "")
        winery = wine.get("winery_name", "")
        search_name = f"{winery} {wine_name}" if winery else wine_name

        # Rate limit: 1 request per second
        time.sleep(1.0)

        result = search_wine_price(search_name, vintage, self.brave_api_key)
        if not result:
            return {
                "xwines_id": xwines_id,
                "vintage": vintage,
                "wine_name": wine_name,
                "winery": winery,
                "estimated_low": price_doc.get("price_low_usd"),
                "estimated_high": price_doc.get("price_high_usd"),
                "estimated_tier": price_doc.get("price_tier"),
                "search_price": None,
                "source": None,
                "status": "no_data",
                "validated_at": datetime.now(timezone.utc),
            }

        search_price = result["search_price"]
        est_low = price_doc.get("price_low_usd", 0)
        est_high = price_doc.get("price_high_usd", 0)

        # Determine accuracy
        if est_low <= search_price <= est_high:
            status = "accurate"
        elif search_price < est_low:
            pct_off = ((est_low - search_price) / search_price) * 100
            status = "overestimated" if pct_off > 30 else "close"
        else:
            pct_off = ((search_price - est_high) / search_price) * 100
            status = "underestimated" if pct_off > 30 else "close"

        return {
            "xwines_id": xwines_id,
            "vintage": vintage,
            "wine_name": wine_name,
            "winery": winery,
            "estimated_low": est_low,
            "estimated_high": est_high,
            "estimated_tier": price_doc.get("price_tier"),
            "search_price": search_price,
            "source": result["source"],
            "snippet": result.get("snippet", ""),
            "url": result.get("url", ""),
            "status": status,
            "validated_at": datetime.now(timezone.utc),
        }

    def run(self) -> None:
        """Run the validation process."""
        if not self.brave_api_key:
            print(
                "Error: No Brave Search API key found. "
                "Set BRAVE_API_KEY environment variable or add to secrets.env"
            )
            sys.exit(1)

        samples = self.sample_prices()
        total = len(samples)

        if total == 0:
            print("No price documents to validate.")
            return

        print(f"\nX-Wines Price Validation")
        print("=" * 50)
        print(f"Database: {self.db_name}")
        print(f"Sample size: {total}")
        if self.tier:
            print(f"Tier filter: {self.tier}")
        print()

        results: list[dict[str, Any]] = []
        for i, doc in enumerate(samples):
            if self._shutdown:
                break

            result = self.validate_sample(doc)
            if result:
                results.append(result)
                # Store in database
                self.validations_col.update_one(
                    {
                        "xwines_id": result["xwines_id"],
                        "vintage": result["vintage"],
                    },
                    {"$set": result},
                    upsert=True,
                )

            print(
                f"\rValidating: {i + 1}/{total}",
                end="",
                flush=True,
            )

        print()
        self._print_report(results)

    def show_report(self) -> None:
        """Show report from existing validation data."""
        results = list(self.validations_col.find({}))
        if not results:
            print("No validation data. Run validation first.")
            return

        self._print_report(results)

    def _print_report(self, results: list[dict[str, Any]]) -> None:
        """Print validation report."""
        total = len(results)
        if total == 0:
            print("No results to report.")
            return

        # Count statuses
        status_counts: dict[str, int] = {}
        for r in results:
            s = r.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        accurate = status_counts.get("accurate", 0)
        close = status_counts.get("close", 0)
        no_data = status_counts.get("no_data", 0)
        overestimated = status_counts.get("overestimated", 0)
        underestimated = status_counts.get("underestimated", 0)

        validated = total - no_data
        good = accurate + close

        print(f"\nValidation Report")
        print("=" * 50)
        print(f"Total sampled: {total}")
        print(f"Web price found: {validated}")
        print(f"No web data: {no_data}")
        print()

        if validated > 0:
            pct_good = (good / validated) * 100
            print(f"Accuracy (within 30% or in range): {pct_good:.1f}%")
            print(f"  Accurate (in range): {accurate} ({accurate / validated * 100:.0f}%)")
            print(f"  Close (<30% off): {close} ({close / validated * 100:.0f}%)")
            print(f"  Overestimated (>30%): {overestimated} ({overestimated / validated * 100:.0f}%)")
            print(f"  Underestimated (>30%): {underestimated} ({underestimated / validated * 100:.0f}%)")

        # Show worst outliers
        outliers = [
            r
            for r in results
            if r.get("status") in ("overestimated", "underestimated")
            and r.get("search_price")
        ]
        if outliers:
            outliers.sort(
                key=lambda r: abs(
                    (r["estimated_low"] + r["estimated_high"]) / 2
                    - r["search_price"]
                ),
                reverse=True,
            )
            print(f"\nTop outliers:")
            for r in outliers[:10]:
                est_mid = (r["estimated_low"] + r["estimated_high"]) / 2
                print(
                    f"  {r['wine_name']}"
                    f"{' ' + str(r['vintage']) if r.get('vintage') else ''}"
                    f" — est: ${r['estimated_low']:.0f}-${r['estimated_high']:.0f}"
                    f" vs actual: ${r['search_price']:.0f}"
                    f" ({r['source']})"
                )

    def shutdown(self) -> None:
        """Signal graceful shutdown."""
        self._shutdown = True

    def close(self) -> None:
        """Close MongoDB connection."""
        self.client.close()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate X-Wines price estimates against web search results",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Number of prices to validate (default: 50)",
    )
    parser.add_argument(
        "--tier",
        choices=["budget", "value", "mid_range", "premium", "luxury", "ultra_premium"],
        default=None,
        help="Validate only prices in this tier",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Show report from existing validations",
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

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    validator = PriceValidator(
        sample_size=args.sample_size,
        tier=args.tier,
        database=args.database,
        verbose=args.verbose,
    )

    def signal_handler(signum: int, frame: Any) -> None:
        print("\n\nShutting down gracefully...")
        validator.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if args.report:
            validator.show_report()
            return 0

        validator.run()
        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        return 130
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=args.verbose)
        return 1
    finally:
        validator.close()


if __name__ == "__main__":
    sys.exit(main())
