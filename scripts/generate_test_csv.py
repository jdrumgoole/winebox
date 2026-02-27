"""Generate a 5000-row test CSV from the X-Wines dataset on production MongoDB.

Matches the column format of tests/data/bc-test-data.csv (Berry Bros & Rudd style).
Each row is a real wine + vintage combination drawn from the X-Wines dataset.

Usage:
    uv run python scripts/generate_test_csv.py
"""

import argparse
import ast
import asyncio
import csv
import os
import random
import sys
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

# Production MongoDB URL - must be set via environment variable
# Example: export XWINES_MONGODB_URL="mongodb+srv://user:pass@host"
PROD_MONGODB_URL = os.environ.get("XWINES_MONGODB_URL", "")
DB_NAME = "winebox"
COLLECTION = "xwines_wines"

OUTPUT_PATH = Path(__file__).parent.parent / "tests" / "data" / "xwines-test-data.csv"
TARGET_ROWS = 5000

# CSV columns mirroring bc-test-data.csv
HEADERS = [
    "Parent ID",
    "Product Code(s)",
    "Country",
    "Region",
    "Vintage",
    "Description",
    "Colour",
    "Maturity",
    "Bottle Format",
    "Bottle Volume",
    "Quantity in Bottles",
    "Eligible for Sale on BBX",
    "Purchase Price per Case",
    "Case Size",
    "Livex Market Price",
    "Wine Searcher Lowest List Price",
    "BBX Last Transaction Price",
    "BBX Lowest Price",
    "BBX Highest Bid",
    "Selling Case Quantity on BBX",
    "Selling Price on BBX",
    "Pending Sale Case Quantity on BBX",
    "Account Payer",
    "Beneficial Owner",
    "Current Status",
    "Provenance",
    "Bottle Condition",
    "Packaging Condition",
    "Wine Condition",
    "Own Goods?",
]

# Map X-Wines wine_type to colour
COLOUR_MAP = {
    "Red": "Red",
    "White": "White",
    "Rosé": "Rosé",
    "Sparkling": "White",
    "Dessert": "White",
    "Dessert/Port": "Red",
}

MATURITY_OPTIONS = ["Not ready", "Drinking now", "Past peak"]
BOTTLE_FORMATS = ["Bottle", "Magnum", "Half Bottle"]
BOTTLE_VOLUMES = {"Bottle": "75cl", "Magnum": "150cl", "Half Bottle": "37.5cl"}
CASE_SIZES = [6, 12]
STATUSES = ["In Bond", "In Bond", "In Bond", "Duty Paid", "In Transit"]
OWNER_NAMES = [
    "Brian Caulfield",
    "Sarah O'Brien",
    "James Murphy",
    "Emma Walsh",
    "Conor Kelly",
]


def parse_vintages(vintages_str: str | None) -> list[int]:
    """Parse the vintages field into a list of numeric years."""
    if not vintages_str:
        return []
    try:
        parsed = ast.literal_eval(vintages_str)
        if isinstance(parsed, list):
            return [int(v) for v in parsed if isinstance(v, (int, float))]
    except (ValueError, SyntaxError):
        pass
    return []


def parse_grapes(grapes_str: str | None) -> str:
    """Parse grapes list string into a readable format."""
    if not grapes_str:
        return ""
    try:
        parsed = ast.literal_eval(grapes_str)
        if isinstance(parsed, list):
            return ", ".join(str(g) for g in parsed if g)
    except (ValueError, SyntaxError):
        pass
    return grapes_str or ""


def generate_product_code(vintage: int, wine_id: int) -> str:
    """Generate a product code similar to bc-test-data format."""
    return f"{vintage}-06-00750-00-{wine_id:07d}"


def generate_parent_id(vintage: int, wine_id: int) -> str:
    """Generate a parent ID similar to bc-test-data format."""
    return f"{vintage}{wine_id:07d}"


def make_description(wine: dict) -> str:
    """Build a description string: 'WineName, Winery, Region, Country'."""
    parts = [wine.get("name", "")]
    if wine.get("winery_name"):
        parts.append(wine["winery_name"])
    if wine.get("region_name"):
        parts.append(wine["region_name"])
    if wine.get("country"):
        parts.append(wine["country"])
    return ", ".join(parts)


def generate_price() -> int:
    """Generate a plausible case purchase price."""
    return random.choice(
        list(range(80, 300, 12))
        + list(range(300, 800, 24))
        + list(range(800, 3000, 100))
    )


def wine_to_rows(wine: dict, rng: random.Random) -> list[dict]:
    """Expand one X-Wines document into one row per vintage."""
    vintages = parse_vintages(wine.get("vintages"))
    if not vintages:
        return []

    wine_id = wine.get("xwines_id", rng.randint(100000, 999999))
    colour = COLOUR_MAP.get(wine.get("wine_type", ""), "Red")
    country = wine.get("country", "")
    region = wine.get("region_name", "")
    description = make_description(wine)
    owner = rng.choice(OWNER_NAMES)

    rows = []
    for vintage in vintages:
        bottle_format = rng.choices(
            BOTTLE_FORMATS, weights=[85, 10, 5], k=1
        )[0]
        case_size = rng.choice(CASE_SIZES)
        quantity = rng.choice([case_size, case_size * 2, case_size // 2]) or case_size
        purchase_price = generate_price()

        # Market prices: some variation around purchase price
        livex = int(purchase_price * rng.uniform(0.8, 2.5))
        ws_price = int(purchase_price * rng.uniform(0.9, 2.0))
        bbx_last = int(purchase_price * rng.uniform(0.85, 2.2))
        bbx_low = int(purchase_price * rng.uniform(0.9, 1.8))
        bbx_bid = int(purchase_price * rng.uniform(0.5, 1.2))

        # Some fields randomly empty (like in the real data)
        selling_qty = rng.choice(["", "", "", str(rng.randint(1, 5))])
        selling_price = (
            str(int(purchase_price * rng.uniform(1.1, 2.5))) if selling_qty else ""
        )
        pending_qty = rng.choice(["", "", "", "", str(rng.randint(1, 3))])

        row = {
            "Parent ID": generate_parent_id(vintage, wine_id),
            "Product Code(s)": generate_product_code(vintage, wine_id),
            "Country": country,
            "Region": region,
            "Vintage": str(vintage),
            "Description": description,
            "Colour": colour,
            "Maturity": rng.choice(MATURITY_OPTIONS),
            "Bottle Format": bottle_format,
            "Bottle Volume": BOTTLE_VOLUMES[bottle_format],
            "Quantity in Bottles": str(quantity),
            "Eligible for Sale on BBX": rng.choice(["Y", "Y", "Y", "N"]),
            "Purchase Price per Case": str(purchase_price),
            "Case Size": str(case_size),
            "Livex Market Price": str(livex),
            "Wine Searcher Lowest List Price": str(ws_price),
            "BBX Last Transaction Price": str(bbx_last) if rng.random() > 0.2 else "",
            "BBX Lowest Price": str(bbx_low),
            "BBX Highest Bid": str(bbx_bid) if rng.random() > 0.3 else "",
            "Selling Case Quantity on BBX": selling_qty,
            "Selling Price on BBX": selling_price,
            "Pending Sale Case Quantity on BBX": pending_qty,
            "Account Payer": owner,
            "Beneficial Owner": owner,
            "Current Status": rng.choice(STATUSES),
            "Provenance": "",
            "Bottle Condition": "",
            "Packaging Condition": "",
            "Wine Condition": "",
            "Own Goods?": "",
        }
        rows.append(row)

    return rows


async def fetch_wines(limit: int = 2000) -> list[dict]:
    """Fetch wines from production X-Wines collection."""
    client = AsyncIOMotorClient(PROD_MONGODB_URL)
    db = client[DB_NAME]
    collection = db[COLLECTION]

    # Sample a diverse set: prioritise wines with many vintages and high ratings
    pipeline = [
        {"$match": {"vintages": {"$ne": None}, "country": {"$ne": None}}},
        {"$sample": {"size": limit}},
    ]

    wines = await collection.aggregate(pipeline).to_list(length=limit)
    client.close()
    return wines


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate test CSV from X-Wines data")
    parser.add_argument(
        "-n", "--rows", type=int, default=TARGET_ROWS, help="Target number of rows"
    )
    parser.add_argument(
        "-o", "--output", type=str, default=str(OUTPUT_PATH), help="Output CSV path"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility"
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    output_path = Path(args.output)

    if not PROD_MONGODB_URL:
        print("Error: XWINES_MONGODB_URL environment variable is not set.", file=sys.stderr)
        print("Set it to the MongoDB connection string for the X-Wines database.", file=sys.stderr)
        sys.exit(1)

    print("Connecting to production X-Wines database...")
    wines = await fetch_wines(limit=2000)
    print(f"Fetched {len(wines)} wines from X-Wines")

    # Generate rows by expanding vintages
    all_rows: list[dict] = []
    rng.shuffle(wines)

    for wine in wines:
        rows = wine_to_rows(wine, rng)
        all_rows.extend(rows)
        if len(all_rows) >= args.rows:
            break

    # If we still need more rows, cycle through wines again with different vintages
    if len(all_rows) < args.rows:
        print(f"  Generated {len(all_rows)} rows from vintages, need {args.rows}...")
        rng.shuffle(wines)
        for wine in wines:
            if len(all_rows) >= args.rows:
                break
            rows = wine_to_rows(wine, rng)
            # Pick a random subset of vintages we haven't used
            for row in rows:
                all_rows.append(row)
                if len(all_rows) >= args.rows:
                    break

    # Trim to exact target
    all_rows = all_rows[: args.rows]

    # Shuffle final order
    rng.shuffle(all_rows)

    # Write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print(f"Wrote {len(all_rows)} rows to {output_path}")

    # Summary stats
    countries = set(r["Country"] for r in all_rows)
    colours = set(r["Colour"] for r in all_rows)
    vintages = [int(r["Vintage"]) for r in all_rows if r["Vintage"].isdigit()]
    print(f"  Countries: {len(countries)}")
    print(f"  Colours: {colours}")
    print(f"  Vintage range: {min(vintages)}-{max(vintages)}")


if __name__ == "__main__":
    asyncio.run(main())
