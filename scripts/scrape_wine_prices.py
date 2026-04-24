#!/usr/bin/env python3
"""Discover wine prices from retail websites using Playwright.

Walks retailer catalogs by navigating category filters and pagination,
storing prices in the wine_prices collection with source="web_scraper".

Usage:
    uv run python scripts/scrape_wine_prices.py [OPTIONS]

Examples:
    uv run python scripts/scrape_wine_prices.py --dry-run --collect 5 --verbose
    uv run python scripts/scrape_wine_prices.py --retailer majestic --collect 100
"""

import argparse
import logging
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, sync_playwright
from pymongo import MongoClient

logger = logging.getLogger(__name__)

# Price sanity bounds
MIN_PRICE = 2.0
MAX_PRICE = 50_000.0

# Responsible scraping
DEFAULT_DELAY = 3.0
MAX_PAGES_PER_COUNTRY = 20


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
    """Store a discovered wine price. Returns True if new wine."""
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

    # Skip if the most recent price from the same retailer has the same price
    prices = doc.get("prices", [])
    for existing in reversed(prices):
        if (existing.get("location", {}).get("shop_name") == wine.retailer_name
                and existing.get("source") == "web_scraper"):
            if existing.get("price") == wine.price and existing.get("currency") == wine.currency:
                return False  # Duplicate — same retailer, same price
            break  # Different price from same retailer — record the change

    prices.append(entry_doc)
    if len(prices) > 20:
        overflow = prices[: len(prices) - 20]
        prices = prices[len(prices) - 20 :]
        history_col.insert_many([{**wine_filter, **e, "archived_at": now} for e in overflow])
    col.update_one({"_id": doc["_id"]}, {"$set": {"prices": prices, "updated_at": now}})
    return False


# ---------------------------------------------------------------------------
# Price / vintage parsing
# ---------------------------------------------------------------------------

def extract_gbp_price(text: str) -> Optional[float]:
    """Extract a GBP price, preferring 'per bottle' over 'Mix Six'."""
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
    """Extract a EUR price (€X.XX or €X,XX) from text."""
    match = re.search(r"€\s?(\d{1,5}(?:[.,]\d{2})?)", text)
    if not match:
        return None
    raw = match.group(1).replace(",", ".")
    price = float(raw)
    return price if MIN_PRICE <= price <= MAX_PRICE else None


def parse_vintage_from_name(name: str) -> tuple[str, Optional[int]]:
    """Extract vintage year from a wine name. Returns (clean_name, vintage)."""
    match = re.search(r"\b((?:19|20)\d{2})(?:/\d{2,4})?\b", name)
    if match:
        vintage = int(match.group(1))
        clean = name[: match.start()].strip().rstrip(",").strip()
        return clean if clean else name, vintage
    return name, None


def classify_wine_type_from_text(text: str) -> Optional[str]:
    """Guess wine type from surrounding text."""
    lower = text.lower()
    for keyword, wtype in [
        ("red wine", "Red"), ("red", "Red"),
        ("white wine", "White"), ("white", "White"),
        ("rosé", "Rosé"), ("rose", "Rosé"),
        ("sparkling", "Sparkling"), ("champagne", "Sparkling"),
        ("prosecco", "Sparkling"), ("cava", "Sparkling"),
    ]:
        if keyword in lower:
            return wtype
    return None


# ---------------------------------------------------------------------------
# Majestic catalog walker
# ---------------------------------------------------------------------------

def _parse_majestic_products(text: str) -> list[tuple[str, float]]:
    """Parse product blocks from Majestic page text.

    Returns list of (wine_name, price_gbp) tuples.
    """
    blocks = re.split(r"\nAdd\s*\n", text)
    results = []
    for block in blocks[1:]:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        raw_name = lines[0]
        price = extract_gbp_price(block)
        if price is None or price < MIN_PRICE or price > MAX_PRICE:
            continue
        results.append((raw_name, price))
    return results


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
    """Walk the Majestic catalog by country filter + pagination.

    Strategy:
    1. Load /wine (the main catalog page)
    2. Accept cookies
    3. Read available country filters from the sidebar
    4. For each country, click its filter link
    5. Parse products on the filtered page
    6. Click "next page" to paginate through all products
    7. Click "All Wines" to reset filter before next country
    """
    print("  Loading catalog page...")
    page.goto("https://www.majestic.co.uk/wine", wait_until="domcontentloaded", timeout=20000)
    time.sleep(delay)

    # Accept cookies
    page.evaluate('document.getElementById("onetrust-accept-btn-handler")?.click()')
    time.sleep(1)

    # Remove cookie overlay from DOM to unblock clicks
    page.evaluate("""
        document.querySelectorAll('#onetrust-consent-sdk, .onetrust-pc-dark-filter').forEach(el => el.remove());
    """)

    # Read country filters from the sidebar
    text = page.inner_text("body")
    country_section = re.search(r"COUNTRY(?:\s+OF\s+ORIGIN)?\n(.*?)(?:BRAND|REGION|GRAPE|PRICE|STYLE|SPECIAL|\Z)", text, re.DOTALL)
    if not country_section:
        print("  Could not find country filter sidebar")
        return

    countries = re.findall(r"(\w[\w\s&]+)\s+\((\d+)\)", country_section.group(1))
    print(f"  Found {len(countries)} countries:")
    for name, count in countries:
        print(f"    {name.strip()}: {count} wines")

    for country_name, country_count in countries:
        if shutdown_flag[0]:
            break
        if collect_target and stats["wines_collected"] >= collect_target:
            break

        country_name = country_name.strip()
        print(f"\n  [{country_name}] ({country_count} wines)")

        # Click the country filter link
        clicked = page.evaluate(f"""() => {{
            const links = Array.from(document.querySelectorAll('a'));
            for (const a of links) {{
                if (a.innerText.trim().startsWith('{country_name} (')) {{
                    a.click();
                    return true;
                }}
            }}
            return false;
        }}""")
        if not clicked:
            if verbose:
                print(f"    Could not click filter for {country_name}")
            continue

        time.sleep(delay)

        # Paginate through this country's wines
        for page_num in range(1, MAX_PAGES_PER_COUNTRY + 1):
            if shutdown_flag[0]:
                break
            if collect_target and stats["wines_collected"] >= collect_target:
                break

            text = page.inner_text("body")
            products = _parse_majestic_products(text)

            if not products:
                break

            if page_num > 1:
                print(f"    Page {page_num}: {len(products)} wines")

            for raw_name, price in products:
                if shutdown_flag[0]:
                    break
                if collect_target and stats["wines_collected"] >= collect_target:
                    break

                clean_name, vintage = parse_vintage_from_name(raw_name)
                stats["wines_processed"] += 1

                wine = DiscoveredWine(
                    name=clean_name,
                    vintage=vintage,
                    wine_type=classify_wine_type_from_text(text),
                    price=price,
                    currency="GBP",
                    retailer_name="Majestic",
                    retailer_country="UK",
                    product_url=page.url,
                )

                if dry_run:
                    stats["wines_collected"] += 1
                    if verbose:
                        v = f" {vintage}" if vintage else ""
                        print(f"    {clean_name}{v}: £{price:.2f}")
                else:
                    try:
                        is_new = store_wine_price(db, wine)
                        stats["prices_stored"] += 1
                        if is_new:
                            stats["wines_collected"] += 1
                            v = f" {vintage}" if vintage else ""
                            print(f"    NEW: {clean_name}{v}: £{price:.2f}")
                    except Exception as e:
                        logger.error("    Store failed: %s", e)
                        stats["errors"] += 1

            # Click next page
            page.evaluate("""
                document.querySelectorAll('#onetrust-consent-sdk, .onetrust-pc-dark-filter').forEach(el => el.remove());
            """)
            has_next = page.evaluate("""() => {
                const next = document.querySelector('li.next-page:not(.disabled) a');
                if (next) { next.click(); return true; }
                return false;
            }""")
            if not has_next:
                break

            time.sleep(delay)

        # Reset filter by clicking "All Wines" or reloading
        page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a'));
            for (const a of links) {
                if (a.innerText.trim() === 'All Wines' || a.innerText.trim() === 'ALL WINES') {
                    a.click();
                    return true;
                }
            }
            return false;
        }""")
        time.sleep(delay)


# ---------------------------------------------------------------------------
# O'Briens catalog walker
# ---------------------------------------------------------------------------

def _parse_obriens_products(page: Page) -> list[tuple[str, float, str]]:
    """Parse product cards from an O'Briens collection page.

    Returns list of (wine_name, price_eur, product_url) tuples.
    """
    cards = page.query_selector_all(".card-wrapper")
    results = []
    for card in cards:
        try:
            title_el = card.query_selector(".card__heading a, .products-productTitle")
            if not title_el:
                continue
            title = title_el.inner_text().strip()
            if not title:
                continue

            # Skip non-wine products (cases, gift cards, accessories)
            lower = title.lower()
            if any(skip in lower for skip in ["case", "gift card", "voucher", "glass", "opener"]):
                continue

            card_text = card.inner_text()
            price = extract_eur_price(card_text)
            if price is None:
                continue

            link_el = card.query_selector('a[href*="/products/"]')
            href = link_el.get_attribute("href") if link_el else ""
            if href and not href.startswith("http"):
                href = f"https://www.obrienswine.ie{href}"

            results.append((title, price, href))
        except Exception:
            continue
    return results


def browse_obriens(
    page: Page,
    delay: float,
    collect_target: Optional[int],
    dry_run: bool,
    verbose: bool,
    db,
    stats: dict,
    shutdown_flag: list,
) -> None:
    """Walk the O'Briens wine catalog by paginating through /collections/wine.

    O'Briens is a Shopify site with simple ?page=N pagination
    and server-rendered product cards.
    """
    page_num = 1

    while True:
        if shutdown_flag[0]:
            break
        if collect_target and stats["wines_collected"] >= collect_target:
            break

        url = f"https://www.obrienswine.ie/collections/wine?page={page_num}"
        if page_num == 1 or verbose:
            print(f"\n  Page {page_num}: {url}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(delay)
        except Exception as e:
            logger.error("  Failed to load page %d: %s", page_num, e)
            stats["errors"] += 1
            break

        products = _parse_obriens_products(page)
        if not products:
            break

        if not verbose:
            print(f"\n  Page {page_num}: {len(products)} wines")

        for title, price, product_url in products:
            if shutdown_flag[0]:
                break
            if collect_target and stats["wines_collected"] >= collect_target:
                break

            clean_name, vintage = parse_vintage_from_name(title)
            wine_type = classify_wine_type_from_text(page.inner_text("body"))
            stats["wines_processed"] += 1

            wine = DiscoveredWine(
                name=clean_name,
                vintage=vintage,
                wine_type=wine_type,
                price=price,
                currency="EUR",
                retailer_name="O'Briens",
                retailer_country="Ireland",
                product_url=product_url,
            )

            if dry_run:
                stats["wines_collected"] += 1
                if verbose:
                    v = f" {vintage}" if vintage else ""
                    print(f"    {clean_name}{v}: €{price:.2f}")
            else:
                try:
                    is_new = store_wine_price(db, wine)
                    stats["prices_stored"] += 1
                    if is_new:
                        stats["wines_collected"] += 1
                        v = f" {vintage}" if vintage else ""
                        print(f"    NEW: {clean_name}{v}: €{price:.2f}")
                except Exception as e:
                    logger.error("    Store failed: %s", e)
                    stats["errors"] += 1

        page_num += 1


# Scraper registry
SCRAPERS = {
    "majestic": {
        "fn": browse_majestic,
        "name": "Majestic (majestic.co.uk)",
    },
    "obriens": {
        "fn": browse_obriens,
        "name": "O'Briens (obrienswine.ie)",
    },
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Discover wine prices from retail websites.")
    parser.add_argument("--database", default="winebox_oat", help="MongoDB database name (default: winebox_oat)")
    parser.add_argument("--collect", type=int, default=None, help="Stop after discovering N unique wines")
    parser.add_argument("--retailer", default="all", choices=["all"] + list(SCRAPERS.keys()))
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"Seconds between pages (default: {DEFAULT_DELAY})")
    parser.add_argument("--honor-robots", action="store_true", help="Check and respect robots.txt")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    shutdown_flag: list[bool] = [False]

    def handle_signal(signum, frame):
        print("\nShutting down gracefully...")
        shutdown_flag[0] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    mongodb_url = get_mongodb_url()
    print(f"Connecting to database: {args.database}")
    client = MongoClient(mongodb_url)
    db = client[args.database]

    active_scrapers = list(SCRAPERS.values()) if args.retailer == "all" else [SCRAPERS[args.retailer]]
    print(f"Retailers: {', '.join(s['name'] for s in active_scrapers)}")
    print(f"Delay: {args.delay}s")
    if args.collect:
        print(f"Collect target: {args.collect} unique wines")
    if args.dry_run:
        print("DRY RUN")
    print("=" * 60)

    stats = {"wines_processed": 0, "wines_collected": 0, "prices_stored": 0, "errors": 0}
    start_time = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "sec-ch-ua": '"Google Chrome";v="120", "Not:A-Brand";v="99", "Chromium";v="120"',
            },
        )
        page = context.new_page()
        # Bound every Playwright operation so an unresponsive retailer site
        # cannot hang the scraper indefinitely. Per-call `goto(timeout=...)`
        # already exists; this sets a global default for everything else
        # (selectors, frames, expects, downloads).
        page.set_default_navigation_timeout(20_000)
        page.set_default_timeout(15_000)

        for scraper_info in active_scrapers:
            if shutdown_flag[0]:
                break
            if args.collect and stats["wines_collected"] >= args.collect:
                break
            print(f"\nBrowsing {scraper_info['name']}...")
            scraper_info["fn"](
                page=page, delay=args.delay, collect_target=args.collect,
                dry_run=args.dry_run, verbose=args.verbose,
                db=db, stats=stats, shutdown_flag=shutdown_flag,
            )

        browser.close()

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"Scraping complete in {elapsed:.1f}s")
    print(f"  Wines discovered:  {stats['wines_processed']}")
    print(f"  New wines:         {stats['wines_collected']}")
    print(f"  Prices stored:     {stats['prices_stored']}")
    print(f"  Errors:            {stats['errors']}")
    if elapsed > 0 and stats["wines_processed"] > 0:
        print(f"  Avg time per wine: {elapsed / stats['wines_processed']:.1f}s")

    client.close()
    return 0 if not stats["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
