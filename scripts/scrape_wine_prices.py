#!/usr/bin/env python3
"""Scrape wine prices from retail websites using Playwright.

Searches target retailers for wines in the database and stores
prices in the wine_prices collection with source="web_scraper".

Usage:
    uv run python scripts/scrape_wine_prices.py [OPTIONS]

Examples:
    uv run python scripts/scrape_wine_prices.py --dry-run --max-wines 3 --verbose
    uv run python scripts/scrape_wine_prices.py --retailer vivino --max-wines 10
    uv run python scripts/scrape_wine_prices.py --retailer all --database winebox-oat
"""

import argparse
import asyncio
import logging
import os
import re
import signal
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, sync_playwright
from pymongo import MongoClient

logger = logging.getLogger(__name__)

# How recently a web_scraper price must exist to skip re-scraping
SKIP_IF_SCRAPED_WITHIN_DAYS = 7

# Price sanity bounds
MIN_PRICE = 2.0
MAX_PRICE = 50_000.0


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ScrapedPrice:
    """A price extracted from a retailer website."""

    price: float
    currency: str
    retailer_name: str
    retailer_country: str
    product_name: str
    product_url: str


@dataclass
class WineQuery:
    """A wine to search for."""

    name: str
    vintage: Optional[int]
    wine_type: Optional[str]


# ---------------------------------------------------------------------------
# MongoDB helpers
# ---------------------------------------------------------------------------

def get_mongodb_url() -> str:
    """Get MongoDB connection URL from environment or .env file."""
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


def get_wines_to_scrape(
    db,
    max_wines: int | None = None,
) -> list[WineQuery]:
    """Fetch unique wines from the wines collection."""
    pipeline = [
        {"$match": {"name": {"$ne": None}}},
        {"$group": {
            "_id": {"name": "$name", "vintage": "$vintage", "wine_type_id": "$wine_type_id"},
        }},
    ]
    if max_wines:
        pipeline.append({"$limit": max_wines})

    results = list(db["wines"].aggregate(pipeline))
    wines = []
    for r in results:
        key = r["_id"]
        wines.append(WineQuery(
            name=key["name"],
            vintage=key.get("vintage"),
            wine_type=key.get("wine_type_id"),
        ))
    return wines


def was_recently_scraped(db, wine: WineQuery) -> bool:
    """Check if this wine has a web_scraper price within the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SKIP_IF_SCRAPED_WITHIN_DAYS)
    doc = db["wine_prices"].find_one({
        "wine_name": wine.name,
        "vintage": wine.vintage,
        "wine_type": wine.wine_type,
        "prices": {
            "$elemMatch": {
                "source": "web_scraper",
                "timestamp": {"$gte": cutoff},
            }
        }
    })
    return doc is not None


def store_price(db, wine: WineQuery, scraped: ScrapedPrice) -> None:
    """Store a scraped price using the async add_price_entry service."""
    from winebox.models.price_capture import ShopLocation
    from winebox.models.wine_price import PriceEntry, PriceSource
    from winebox.services.price_service import add_price_entry

    entry = PriceEntry(
        timestamp=datetime.now(timezone.utc),
        source=PriceSource.WEB_SCRAPER,
        price=scraped.price,
        currency=scraped.currency,
        owner_id=None,
        location=ShopLocation(
            shop_name=scraped.retailer_name,
            country=scraped.retailer_country,
        ),
        notes=f"Scraped from {scraped.product_url}",
    )

    asyncio.run(add_price_entry(
        wine_name=wine.name,
        vintage=wine.vintage,
        wine_type=wine.wine_type,
        entry=entry,
    ))


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------

# Regex patterns for price extraction
PRICE_PATTERNS = [
    # $29.99 or $ 29.99
    re.compile(r"\$\s?(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)"),
    # €29,99 or €29.99 or € 29,99
    re.compile(r"€\s?(\d{1,5}(?:[.,]\d{2,3})*)"),
    # £29.99 or £ 29.99
    re.compile(r"£\s?(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)"),
]

CURRENCY_BY_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP"}


def extract_price_from_text(text: str) -> Optional[tuple[float, str]]:
    """Extract the first valid price and currency from text.

    Returns:
        Tuple of (price, currency) or None if no valid price found.
    """
    for symbol, currency in CURRENCY_BY_SYMBOL.items():
        for pattern in PRICE_PATTERNS:
            if symbol not in str(pattern.pattern):
                continue
            match = pattern.search(text)
            if match:
                raw = match.group(1)
                # Normalise: remove thousands separators, fix decimal
                if currency == "EUR" and "," in raw and "." not in raw:
                    # €29,99 → 29.99
                    raw = raw.replace(",", ".")
                else:
                    raw = raw.replace(",", "")
                try:
                    price = float(raw)
                    if MIN_PRICE <= price <= MAX_PRICE:
                        return (price, currency)
                except ValueError:
                    continue
    return None


def build_search_query(wine: WineQuery) -> str:
    """Build a search query string from wine details."""
    parts = [wine.name]
    if wine.vintage:
        parts.append(str(wine.vintage))
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Retailer scrapers
# ---------------------------------------------------------------------------

def scrape_vivino(page: Page, wine: WineQuery, delay: float) -> Optional[ScrapedPrice]:
    """Scrape a price from vivino.com.

    Vivino doesn't show prices on the search results page. We search,
    click through to the first matching wine's detail page, then extract
    the price from there.
    """
    query = build_search_query(wine)
    url = f"https://www.vivino.com/search/wines?q={urllib.parse.quote(query)}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(delay)

        # Find the first wine link in search results
        link = page.query_selector('a[href*="/w/"]')
        if not link:
            return None

        href = link.get_attribute("href") or ""
        product_url = f"https://www.vivino.com{href}" if not href.startswith("http") else href

        # Get wine name from the link text for match validation
        product_name = link.inner_text().strip()[:200]

        # Navigate to the product page
        page.goto(product_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(delay)

        # Extract price from the product page body text
        body_text = page.inner_text("body")

        # Vivino shows prices like "Available prices ... starting at around €225"
        # or direct prices like "€29.99" / "$45.00"
        result = extract_price_from_text(body_text)
        if not result:
            return None

        price, currency = result

        return ScrapedPrice(
            price=price,
            currency=currency,
            retailer_name="Vivino",
            retailer_country="Global",
            product_name=product_name,
            product_url=product_url,
        )
    except Exception as e:
        logger.debug("Vivino scrape failed for %s: %s", query, e)
        return None


def scrape_wine_com(page: Page, wine: WineQuery, delay: float) -> Optional[ScrapedPrice]:
    """Scrape a price from wine.com."""
    query = build_search_query(wine)
    url = f"https://www.wine.com/search?searchText={urllib.parse.quote(query)}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(delay)

        # Wait for product listings
        page.wait_for_selector('[class*="prodItem"], [class*="product-card"], .searchResults', timeout=8000)

        # Get page text and look for prices
        cards = page.query_selector_all('[class*="prodItem"], [class*="product-card"]')
        if not cards:
            # Fallback: get all text from results area
            results_area = page.query_selector('.searchResults, [class*="search-results"], main')
            if not results_area:
                return None
            text = results_area.inner_text()
            result = extract_price_from_text(text)
            if not result:
                return None
            price, currency = result
            return ScrapedPrice(
                price=price, currency=currency,
                retailer_name="Wine.com", retailer_country="US",
                product_name=query, product_url=url,
            )

        card = cards[0]
        card_text = card.inner_text()
        result = extract_price_from_text(card_text)
        if not result:
            return None

        price, currency = result
        name_el = card.query_selector('[class*="prodName"], [class*="product-name"], a')
        product_name = name_el.inner_text() if name_el else card_text[:100]

        link_el = card.query_selector("a[href]")
        product_url = link_el.get_attribute("href") if link_el else url
        if product_url and not product_url.startswith("http"):
            product_url = f"https://www.wine.com{product_url}"

        return ScrapedPrice(
            price=price, currency=currency,
            retailer_name="Wine.com", retailer_country="US",
            product_name=product_name.strip(), product_url=product_url or url,
        )
    except Exception as e:
        logger.debug("Wine.com scrape failed for %s: %s", query, e)
        return None


def scrape_totalwine(page: Page, wine: WineQuery, delay: float) -> Optional[ScrapedPrice]:
    """Scrape a price from totalwine.com."""
    query = build_search_query(wine)
    url = f"https://www.totalwine.com/search/all?text={urllib.parse.quote(query)}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(delay)

        page.wait_for_selector('[class*="product"], [data-testid*="product"]', timeout=8000)

        cards = page.query_selector_all('[class*="productCard"], [class*="product-card"], [data-testid*="product"]')
        if not cards:
            body_text = page.inner_text("body")
            result = extract_price_from_text(body_text[:2000])
            if not result:
                return None
            price, currency = result
            return ScrapedPrice(
                price=price, currency=currency,
                retailer_name="Total Wine", retailer_country="US",
                product_name=query, product_url=url,
            )

        card = cards[0]
        card_text = card.inner_text()
        result = extract_price_from_text(card_text)
        if not result:
            return None

        price, currency = result
        name_el = card.query_selector('[class*="title"], [class*="name"], a')
        product_name = name_el.inner_text() if name_el else card_text[:100]

        link_el = card.query_selector("a[href]")
        product_url = link_el.get_attribute("href") if link_el else url
        if product_url and not product_url.startswith("http"):
            product_url = f"https://www.totalwine.com{product_url}"

        return ScrapedPrice(
            price=price, currency=currency,
            retailer_name="Total Wine", retailer_country="US",
            product_name=product_name.strip(), product_url=product_url or url,
        )
    except Exception as e:
        logger.debug("Total Wine scrape failed for %s: %s", query, e)
        return None


def scrape_majestic(page: Page, wine: WineQuery, delay: float) -> Optional[ScrapedPrice]:
    """Scrape a price from majestic.co.uk."""
    query = build_search_query(wine)
    url = f"https://www.majestic.co.uk/search?q={urllib.parse.quote(query)}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(delay)

        page.wait_for_selector('[class*="product"], [class*="search-result"]', timeout=8000)

        cards = page.query_selector_all('[class*="product-card"], [class*="product-item"], [class*="search-result"]')
        if not cards:
            body_text = page.inner_text("body")
            result = extract_price_from_text(body_text[:2000])
            if not result:
                return None
            price, currency = result
            return ScrapedPrice(
                price=price, currency=currency,
                retailer_name="Majestic", retailer_country="UK",
                product_name=query, product_url=url,
            )

        card = cards[0]
        card_text = card.inner_text()
        result = extract_price_from_text(card_text)
        if not result:
            return None

        price, currency = result
        name_el = card.query_selector('[class*="title"], [class*="name"], a')
        product_name = name_el.inner_text() if name_el else card_text[:100]

        link_el = card.query_selector("a[href]")
        product_url = link_el.get_attribute("href") if link_el else url
        if product_url and not product_url.startswith("http"):
            product_url = f"https://www.majestic.co.uk{product_url}"

        return ScrapedPrice(
            price=price, currency=currency,
            retailer_name="Majestic", retailer_country="UK",
            product_name=product_name.strip(), product_url=product_url or url,
        )
    except Exception as e:
        logger.debug("Majestic scrape failed for %s: %s", query, e)
        return None


# Registry of available scrapers
SCRAPERS: dict[str, dict] = {
    "vivino": {
        "fn": scrape_vivino,
        "name": "Vivino",
    },
    "wine.com": {
        "fn": scrape_wine_com,
        "name": "Wine.com",
    },
    "totalwine": {
        "fn": scrape_totalwine,
        "name": "Total Wine",
    },
    "majestic": {
        "fn": scrape_majestic,
        "name": "Majestic",
    },
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape wine prices from retail websites.",
    )
    parser.add_argument(
        "--database",
        default="winebox-oat",
        help="MongoDB database name (default: winebox-oat)",
    )
    parser.add_argument(
        "--max-wines",
        type=int,
        default=None,
        help="Maximum number of wines to process",
    )
    parser.add_argument(
        "--retailer",
        default="all",
        choices=["all"] + list(SCRAPERS.keys()),
        help="Target retailer or 'all' (default: all)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between page loads (default: 2.0)",
    )
    parser.add_argument(
        "--collect",
        type=int,
        default=None,
        help="Stop after collecting prices for N unique wines",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    # Suppress noisy pymongo debug logs
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Graceful shutdown
    shutdown_flag: list[bool] = [False]

    def handle_signal(signum, frame):
        print("\nShutting down gracefully...")
        shutdown_flag[0] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Connect to MongoDB
    mongodb_url = get_mongodb_url()
    print(f"Connecting to database: {args.database}")
    client = MongoClient(mongodb_url)
    db = client[args.database]

    # Initialise async database for add_price_entry
    if not args.dry_run:
        from pymongo import AsyncMongoClient
        from winebox.database import init_db
        async_client = AsyncMongoClient(mongodb_url)
        asyncio.run(init_db(
            mongo_client=async_client,
            mongodb_database=args.database,
            skip_indexes=True,
        ))

    # Fetch wines
    wines = get_wines_to_scrape(db, max_wines=args.max_wines)
    print(f"Found {len(wines)} wines to look up")

    # Select scrapers
    if args.retailer == "all":
        active_scrapers = list(SCRAPERS.values())
    else:
        active_scrapers = [SCRAPERS[args.retailer]]

    scraper_names = ", ".join(s["name"] for s in active_scrapers)
    print(f"Retailers: {scraper_names}")
    print(f"Delay: {args.delay}s between requests")
    if args.dry_run:
        print("DRY RUN — no prices will be stored")
    print("=" * 60)

    if args.collect:
        print(f"Will stop after collecting prices for {args.collect} unique wines")

    # Stats
    stats = {
        "wines_processed": 0,
        "wines_skipped": 0,
        "prices_found": 0,
        "prices_stored": 0,
        "errors": 0,
        "wines_collected": 0,
    }

    start_time = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for i, wine in enumerate(wines):
            if shutdown_flag[0]:
                print("\nInterrupted — stopping.")
                break

            # Check if we've collected enough unique wines
            if args.collect and stats["wines_collected"] >= args.collect:
                print(f"\nReached collection target of {args.collect} wines — stopping.")
                break

            label = f"{wine.name}"
            if wine.vintage:
                label += f" {wine.vintage}"
            print(f"\n[{i + 1}/{len(wines)}] {label}")

            # Skip if recently scraped
            if not args.dry_run and was_recently_scraped(db, wine):
                print(f"  Skipped — scraped within last {SKIP_IF_SCRAPED_WITHIN_DAYS} days")
                stats["wines_skipped"] += 1
                continue

            stats["wines_processed"] += 1
            found_price_for_this_wine = False

            for scraper_info in active_scrapers:
                if shutdown_flag[0]:
                    break

                scraper_fn = scraper_info["fn"]
                retailer_name = scraper_info["name"]

                try:
                    result = scraper_fn(page, wine, args.delay)
                except Exception as e:
                    logger.error("  %s: error — %s", retailer_name, e)
                    stats["errors"] += 1
                    continue

                if result is None:
                    if args.verbose:
                        print(f"  {retailer_name}: no price found")
                    continue

                stats["prices_found"] += 1
                found_price_for_this_wine = True
                print(
                    f"  {retailer_name}: {result.currency} {result.price:.2f}"
                    f" — {result.product_name[:60]}"
                )

                if not args.dry_run:
                    try:
                        store_price(db, wine, result)
                        stats["prices_stored"] += 1
                    except Exception as e:
                        logger.error("  Failed to store: %s", e)
                        stats["errors"] += 1

            if found_price_for_this_wine:
                stats["wines_collected"] += 1

        browser.close()

    # Report
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"Scraping complete in {elapsed:.1f}s")
    print(f"  Wines processed: {stats['wines_processed']}")
    print(f"  Wines collected: {stats['wines_collected']}")
    print(f"  Wines skipped:   {stats['wines_skipped']}")
    print(f"  Prices found:    {stats['prices_found']}")
    print(f"  Prices stored:   {stats['prices_stored']}")
    print(f"  Errors:          {stats['errors']}")

    client.close()
    return 0 if not stats["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
