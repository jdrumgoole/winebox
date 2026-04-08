#!/usr/bin/env python3
"""Discover wine prices from retail websites using Playwright.

Browses retailer sites to discover wines and their prices, storing
them in the wine_prices collection with source="web_scraper".

Usage:
    uv run python scripts/scrape_wine_prices.py [OPTIONS]

Examples:
    uv run python scripts/scrape_wine_prices.py --dry-run --collect 5 --verbose
    uv run python scripts/scrape_wine_prices.py --retailer majestic --collect 20
    uv run python scripts/scrape_wine_prices.py --retailer vivino --collect 50
"""

import argparse
import logging
import os
import re
import signal
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, sync_playwright
from pymongo import MongoClient

logger = logging.getLogger(__name__)


class RateLimiter:
    """Adaptive rate limiter with exponential backoff on errors."""

    def __init__(self, base_delay: float) -> None:
        self.base_delay = base_delay
        self.current_delay = base_delay
        self.consecutive_errors = 0
        self.total_requests = 0

    def wait(self) -> None:
        """Wait before the next request."""
        time.sleep(self.current_delay)
        self.total_requests += 1

    def record_success(self) -> None:
        """Reset backoff on a successful request."""
        self.consecutive_errors = 0
        self.current_delay = self.base_delay

    def record_error(self) -> None:
        """Increase delay on consecutive errors."""
        self.consecutive_errors += 1
        if self.consecutive_errors >= MAX_ERRORS_BEFORE_BACKOFF:
            self.current_delay = min(
                self.current_delay * BACKOFF_MULTIPLIER,
                MAX_DELAY,
            )
            logger.warning(
                "  %d consecutive errors — backing off to %.1fs delay",
                self.consecutive_errors, self.current_delay,
            )


def check_robots_txt(page: Page, base_url: str) -> bool:
    """Check if robots.txt allows scraping. Returns True if allowed or unclear."""
    robots_url = f"{base_url}/robots.txt"
    try:
        page.goto(robots_url, wait_until="domcontentloaded", timeout=10000)
        text = page.inner_text("body").lower()
        # Check for blanket disallow for all user agents
        if "user-agent: *" in text and "disallow: /" in text:
            # Check if it's a blanket block (Disallow: /) vs specific paths
            lines = text.split("\n")
            in_star_block = False
            for line in lines:
                line = line.strip()
                if line == "user-agent: *":
                    in_star_block = True
                elif line.startswith("user-agent:"):
                    in_star_block = False
                elif in_star_block and line == "disallow: /":
                    return False
        return True
    except Exception:
        # If we can't read robots.txt, proceed cautiously
        return True

# Price sanity bounds
MIN_PRICE = 2.0
MAX_PRICE = 50_000.0

# Responsible scraping settings
DEFAULT_DELAY = 3.0          # seconds between page loads
MAX_PAGES_PER_CATEGORY = 20  # don't crawl deeper than this per category
MAX_ERRORS_BEFORE_BACKOFF = 3  # consecutive errors before increasing delay
BACKOFF_MULTIPLIER = 2.0     # multiply delay on consecutive errors
MAX_DELAY = 30.0             # cap on backoff delay


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DiscoveredWine:
    """A wine discovered on a retailer website."""

    name: str
    vintage: Optional[int]
    wine_type: Optional[str]
    price: float
    currency: str
    retailer_name: str
    retailer_country: str
    product_url: str


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


def store_wine_price(db, wine: DiscoveredWine) -> bool:
    """Store a discovered wine price. Returns True if new wine, False if appended."""
    now = datetime.now(timezone.utc)
    col = db["wine_prices"]
    history_col = db["wine_prices_history"]

    entry_doc = {
        "timestamp": now,
        "source": "web_scraper",
        "price": wine.price,
        "currency": wine.currency,
        "owner_id": None,
        "location": {
            "shop_name": wine.retailer_name,
            "town_city": None,
            "state_county": None,
            "country": wine.retailer_country,
        },
        "coordinates": None,
        "notes": f"Discovered on {wine.retailer_name}",
        "photo_path": None,
        "capture_type": None,
    }

    wine_filter = {
        "wine_name": wine.name,
        "vintage": wine.vintage,
        "wine_type": wine.wine_type,
    }

    doc = col.find_one(wine_filter)

    if doc is None:
        col.insert_one({
            **wine_filter,
            "prices": [entry_doc],
            "created_at": now,
            "updated_at": now,
        })
        return True

    # Append to existing
    prices = doc.get("prices", [])
    prices.append(entry_doc)

    if len(prices) > 20:
        overflow_count = len(prices) - 20
        overflow = prices[:overflow_count]
        prices = prices[overflow_count:]
        history_docs = [{**wine_filter, **entry, "archived_at": now} for entry in overflow]
        history_col.insert_many(history_docs)

    col.update_one(
        {"_id": doc["_id"]},
        {"$set": {"prices": prices, "updated_at": now}},
    )
    return False


# ---------------------------------------------------------------------------
# Price / vintage parsing
# ---------------------------------------------------------------------------

def extract_gbp_price(text: str) -> Optional[float]:
    """Extract a GBP price from text, preferring 'per bottle' over 'Mix Six'."""
    per_bottle = re.search(r"£(\d{1,5}(?:\.\d{2})?)\s*per bottle", text)
    if per_bottle:
        return float(per_bottle.group(1))
    mix_six = re.search(r"£(\d{1,5}(?:\.\d{2})?)\s*Mix Six", text)
    if mix_six:
        return float(mix_six.group(1))
    any_price = re.search(r"£(\d{1,5}(?:\.\d{2})?)", text)
    if any_price:
        return float(any_price.group(1))
    return None


def extract_eur_price(text: str) -> Optional[float]:
    """Extract a EUR price from text."""
    match = re.search(r"€\s?(\d{1,5}(?:[.,]\d{2})?)", text)
    if not match:
        return None
    raw = match.group(1).replace(",", ".")
    return float(raw)


def extract_usd_price(text: str) -> Optional[float]:
    """Extract a USD price from text."""
    match = re.search(r"\$\s?(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)", text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def parse_vintage_from_name(name: str) -> tuple[str, Optional[int]]:
    """Extract vintage year from a wine name if present.

    Returns (clean_name, vintage) tuple.
    """
    # Match 4-digit year (1900-2099) at end or in the middle
    match = re.search(r"\b((?:19|20)\d{2})(?:/\d{2,4})?\b", name)
    if match:
        vintage = int(match.group(1))
        clean = name[:match.start()].strip().rstrip(",").strip()
        if not clean:
            clean = name
        return clean, vintage
    return name, None


def classify_wine_type(text: str) -> Optional[str]:
    """Guess the wine type from surrounding text."""
    lower = text.lower()
    if "red wine" in lower or "red" in lower:
        return "Red"
    if "white wine" in lower or "white" in lower:
        return "White"
    if "rosé" in lower or "rose wine" in lower:
        return "Rosé"
    if "sparkling" in lower or "champagne" in lower or "prosecco" in lower or "cava" in lower:
        return "Sparkling"
    return None


# ---------------------------------------------------------------------------
# Majestic scraper (browse via search)
# ---------------------------------------------------------------------------

MAJESTIC_CATEGORIES = [
    ("red wine", "Red"),
    ("bordeaux", "Red"),
    ("rioja", "Red"),
    ("pinot noir", "Red"),
    ("malbec", "Red"),
    ("white wine", "White"),
    ("chablis", "White"),
    ("sauvignon blanc", "White"),
    ("chardonnay", "White"),
    ("rosé wine", "Rosé"),
    ("champagne", "Sparkling"),
    ("prosecco", "Sparkling"),
    ("sparkling wine", "Sparkling"),
]

MAJESTIC_PAGE_SIZE = 18  # Majestic's default; larger values break pagination


def browse_majestic(
    page: Page,
    delay: float,
    collect_target: Optional[int],
    dry_run: bool,
    verbose: bool,
    db,
    stats: dict,
    shutdown_flag: list,
) -> None:
    """Browse majestic.co.uk categories and extract wine prices."""
    limiter = RateLimiter(delay)

    for search_term, wine_type in MAJESTIC_CATEGORIES:
        if shutdown_flag[0]:
            break
        if collect_target and stats["wines_collected"] >= collect_target:
            break

        # Load first page of this category
        url = f"https://www.majestic.co.uk/search?q={urllib.parse.quote(search_term)}"
        print(f"\n  [{wine_type}] {url}")

        limiter.wait()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            limiter.record_success()
            # Dismiss cookie consent overlay if present (blocks all clicks)
            accept_btn = page.query_selector("#onetrust-accept-btn-handler, button:has-text('Accept')")
            if accept_btn:
                try:
                    accept_btn.click(timeout=3000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass
        except Exception as e:
            logger.error("  Failed to load: %s", e)
            limiter.record_error()
            stats["errors"] += 1
            continue

        for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
            if shutdown_flag[0]:
                break
            if collect_target and stats["wines_collected"] >= collect_target:
                break

            if page_num > 1:
                print(f"  [{wine_type}] Page {page_num}")

            text = page.inner_text("body")

            total_match = re.search(r"(\d+)\s*Products? found", text)
            if not total_match:
                break

            # Parse product blocks
            blocks = re.split(r"\nAdd\s*\n", text)
            wines_on_page = 0

            for block in blocks[1:]:
                if shutdown_flag[0]:
                    break
                if collect_target and stats["wines_collected"] >= collect_target:
                    break

                lines = [l.strip() for l in block.split("\n") if l.strip()]
                if not lines:
                    continue

                raw_name = lines[0]
                price = extract_gbp_price(block)
                if price is None or price < MIN_PRICE or price > MAX_PRICE:
                    continue

                clean_name, vintage = parse_vintage_from_name(raw_name)
                wines_on_page += 1
                stats["wines_processed"] += 1

                wine = DiscoveredWine(
                    name=clean_name,
                    vintage=vintage,
                    wine_type=wine_type,
                    price=price,
                    currency="GBP",
                    retailer_name="Majestic",
                    retailer_country="UK",
                    product_url=page.url,
                )

                if verbose:
                    v = f" {vintage}" if vintage else ""
                    print(f"    {clean_name}{v}: £{price:.2f}")

                if not dry_run:
                    try:
                        is_new = store_wine_price(db, wine)
                        stats["prices_stored"] += 1
                        if is_new:
                            stats["wines_collected"] += 1
                            if not verbose:
                                v = f" {vintage}" if vintage else ""
                                print(f"    NEW: {clean_name}{v}: £{price:.2f}")
                    except Exception as e:
                        logger.error("    Failed to store: %s", e)
                        stats["errors"] += 1
                else:
                    stats["wines_collected"] += 1

            if wines_on_page == 0:
                break

            # Click the next page button in Majestic's JS pagination
            next_btn = page.query_selector("li.next-page:not(.disabled)")
            if not next_btn:
                break

            limiter.wait()
            try:
                next_btn.click()
                page.wait_for_timeout(2000)
                limiter.record_success()
            except Exception:
                break


# ---------------------------------------------------------------------------
# Vivino scraper (browse via search)
# ---------------------------------------------------------------------------

VIVINO_CATEGORIES = [
    ("red wine", "Red"),
    ("white wine", "White"),
    ("rosé wine", "Rosé"),
    ("sparkling wine", "Sparkling"),
    ("champagne", "Sparkling"),
]


def browse_vivino(
    page: Page,
    delay: float,
    collect_target: Optional[int],
    dry_run: bool,
    verbose: bool,
    db,
    stats: dict,
    shutdown_flag: list,
) -> None:
    """Browse vivino.com by following wine links from search results."""
    limiter = RateLimiter(delay)

    for search_term, wine_type in VIVINO_CATEGORIES:
        if shutdown_flag[0]:
            break
        if collect_target and stats["wines_collected"] >= collect_target:
            break

        page_num = 1
        while True:
            if shutdown_flag[0]:
                break
            if collect_target and stats["wines_collected"] >= collect_target:
                break

            if page_num > MAX_PAGES_PER_CATEGORY:
                if verbose:
                    print(f"    Reached page limit ({MAX_PAGES_PER_CATEGORY}) — next category")
                break

            url = (
                f"https://www.vivino.com/search/wines?q={urllib.parse.quote(search_term)}"
                f"&start={((page_num - 1) * 25) + 1}"
            )
            print(f"\n  [{wine_type}] Page {page_num}: {url}")

            limiter.wait()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                limiter.record_success()
            except Exception as e:
                logger.error("  Failed to load page: %s", e)
                limiter.record_error()
                stats["errors"] += 1
                break

            # Find all wine links
            links = page.query_selector_all('a[href*="/w/"]')
            if not links:
                break

            # Collect hrefs first to avoid stale element issues
            hrefs = []
            for link in links:
                try:
                    href = link.get_attribute("href")
                    name_text = link.inner_text().strip()
                    if href and name_text:
                        full_url = f"https://www.vivino.com{href}" if not href.startswith("http") else href
                        hrefs.append((full_url, name_text))
                except Exception:
                    continue

            if not hrefs:
                break

            wines_on_page = 0
            for wine_url, raw_name in hrefs:
                if shutdown_flag[0]:
                    break
                if collect_target and stats["wines_collected"] >= collect_target:
                    break

                # Visit wine detail page to get price
                limiter.wait()
                try:
                    page.goto(wine_url, wait_until="domcontentloaded", timeout=15000)
                    limiter.record_success()
                except Exception:
                    limiter.record_error()
                    continue

                body_text = page.inner_text("body")
                price = extract_eur_price(body_text)
                if price is None:
                    price = extract_usd_price(body_text)
                    currency = "USD" if price else "EUR"
                else:
                    currency = "EUR"

                if price is None or price < MIN_PRICE or price > MAX_PRICE:
                    if verbose:
                        print(f"    {raw_name[:60]}: no price")
                    continue

                clean_name, vintage = parse_vintage_from_name(raw_name)
                wines_on_page += 1
                stats["wines_processed"] += 1

                wine = DiscoveredWine(
                    name=clean_name,
                    vintage=vintage,
                    wine_type=wine_type,
                    price=price,
                    currency=currency,
                    retailer_name="Vivino",
                    retailer_country="Global",
                    product_url=wine_url,
                )

                if verbose:
                    v = f" {vintage}" if vintage else ""
                    print(f"    {clean_name}{v}: {currency} {price:.2f}")

                if not dry_run:
                    try:
                        is_new = store_wine_price(db, wine)
                        stats["prices_stored"] += 1
                        if is_new:
                            stats["wines_collected"] += 1
                            if not verbose:
                                v = f" {vintage}" if vintage else ""
                                print(f"    NEW: {clean_name}{v}: {currency} {price:.2f}")
                    except Exception as e:
                        logger.error("    Failed to store: %s", e)
                        stats["errors"] += 1
                else:
                    stats["wines_collected"] += 1

            if wines_on_page == 0:
                break

            page_num += 1


# Registry of available scrapers
SCRAPERS: dict[str, dict] = {
    "majestic": {
        "fn": browse_majestic,
        "name": "Majestic (majestic.co.uk)",
    },
    "vivino": {
        "fn": browse_vivino,
        "name": "Vivino (vivino.com)",
    },
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover wine prices from retail websites.",
    )
    parser.add_argument(
        "--database",
        default="winebox-oat",
        help="MongoDB database name (default: winebox-oat)",
    )
    parser.add_argument(
        "--collect",
        type=int,
        default=None,
        help="Stop after discovering N unique wines (default: unlimited)",
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
        default=DEFAULT_DELAY,
        help=f"Seconds to wait between page loads (default: {DEFAULT_DELAY})",
    )
    parser.add_argument("--honor-robots", action="store_true", help="Check and respect robots.txt")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
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

    # Select scrapers
    if args.retailer == "all":
        active_scrapers = list(SCRAPERS.values())
    else:
        active_scrapers = [SCRAPERS[args.retailer]]

    scraper_names = ", ".join(s["name"] for s in active_scrapers)
    print(f"Retailers: {scraper_names}")
    print(f"Delay: {args.delay}s between requests")
    if args.collect:
        print(f"Collect target: {args.collect} unique wines")
    if args.dry_run:
        print("DRY RUN — no prices will be stored")
    print("=" * 60)

    stats = {
        "wines_processed": 0,
        "wines_collected": 0,
        "prices_stored": 0,
        "errors": 0,
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

        # Map retailer keys to base URLs for robots.txt check
        robots_urls = {
            "majestic": "https://www.majestic.co.uk",
            "vivino": "https://www.vivino.com",
        }

        for scraper_info in active_scrapers:
            if shutdown_flag[0]:
                break
            if args.collect and stats["wines_collected"] >= args.collect:
                break

            # Check robots.txt if --honor-robots is set
            if args.honor_robots:
                retailer_key = next(
                    (k for k, v in SCRAPERS.items() if v is scraper_info), None
                )
                base_url = robots_urls.get(retailer_key, "")
                if base_url and not check_robots_txt(page, base_url):
                    print(f"\n  {scraper_info['name']}: robots.txt disallows scraping — skipping.")
                    continue

            print(f"\nBrowsing {scraper_info['name']}...")
            scraper_fn = scraper_info["fn"]
            scraper_fn(
                page=page,
                delay=args.delay,
                collect_target=args.collect,
                dry_run=args.dry_run,
                verbose=args.verbose,
                db=db,
                stats=stats,
                shutdown_flag=shutdown_flag,
            )

        browser.close()

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"Scraping complete in {elapsed:.1f}s")
    print(f"  Wines discovered:  {stats['wines_processed']}")
    print(f"  New wines:         {stats['wines_collected']}")
    print(f"  Prices stored:     {stats['prices_stored']}")
    print(f"  Errors:            {stats['errors']}")
    if elapsed > 0 and stats['wines_processed'] > 0:
        rate = elapsed / stats['wines_processed']
        print(f"  Avg time per wine: {rate:.1f}s")

    client.close()
    return 0 if not stats["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
