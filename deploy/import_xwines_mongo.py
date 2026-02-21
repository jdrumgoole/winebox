#!/usr/bin/env python3
"""Import X-Wines dataset into MongoDB.

Standalone script uploaded to production server by deploy/xwines.py.
Uses pymongo directly to bulk-insert wines and ratings from CSV files.

Drops the xwines_wines collection before importing to prevent duplicates.
Streams the ratings CSV to avoid loading the full 1GB+ file into memory.

Usage (on the server):
    python /opt/winebox/import_xwines.py --version full --force
    python /opt/winebox/import_xwines.py --version test --force
"""

import argparse
import csv
import io
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from pymongo import MongoClient, UpdateOne

# Dataset URLs (for test version only — full/slim use local CSVs)
GITHUB_BASE = "https://raw.githubusercontent.com/rogerioxavier/X-Wines/main/Dataset/last"

DATASET_VERSIONS = {
    "test": {
        "wines_url": f"{GITHUB_BASE}/XWines_Test_100_wines.csv",
        "ratings_url": f"{GITHUB_BASE}/XWines_Test_1K_ratings.csv",
        "expected_wines": 100,
        "expected_ratings": 1000,
        "description": "Test dataset (100 wines, 1K ratings)",
    },
    "slim": {
        "wines_url": None,
        "ratings_url": None,
        "expected_wines": 1007,
        "expected_ratings": 150000,
        "description": "Slim dataset (1,007 wines, 150K ratings)",
    },
    "full": {
        "wines_url": None,
        "ratings_url": None,
        "expected_wines": 100646,
        "expected_ratings": 21013536,
        "description": "Full dataset (100K wines, 21M ratings)",
    },
}

DATA_DIR = Path("/opt/winebox/data/xwines")


class ImportInterrupted(Exception):
    """Raised when import is interrupted by Ctrl+C."""


def signal_handler(signum: int, frame: Any) -> None:
    """Handle Ctrl+C gracefully."""
    raise ImportInterrupted()


def download_csv(url: str, description: str = "data") -> str:
    """Download CSV file from URL.

    Args:
        url: URL to download from
        description: Description for progress messages

    Returns:
        CSV content as string
    """
    print(f"Downloading {description}...")
    print(f"  URL: {url}")

    try:
        with urlopen(url, timeout=60) as response:
            total_size = response.headers.get("content-length")
            if total_size:
                print(f"  Size: {int(total_size) / 1024:.1f} KB")
            content = response.read()
            print(f"  Downloaded: {len(content) / 1024:.1f} KB")
            return content.decode("utf-8")
    except HTTPError as e:
        print(f"  Error: HTTP {e.code} - {e.reason}")
        raise
    except URLError as e:
        print(f"  Error: {e.reason}")
        raise


def parse_csv_wines(csv_content: str) -> list[dict[str, Any]]:
    """Parse wines CSV content into list of documents.

    Args:
        csv_content: Raw CSV content as string

    Returns:
        List of wine document dicts
    """
    wines = []
    reader = csv.DictReader(io.StringIO(csv_content))

    for row in reader:
        wine: dict[str, Any] = {
            "xwines_id": int(row.get("WineID", 0)),
            "name": row.get("WineName", "").strip(),
            "wine_type": row.get("Type", "").strip(),
            "elaborate": row.get("Elaborate", "").strip() or None,
            "grapes": row.get("Grapes", "").strip() or None,
            "harmonize": row.get("Harmonize", "").strip() or None,
            "abv": float(row["ABV"]) if row.get("ABV") else None,
            "body": row.get("Body", "").strip() or None,
            "acidity": row.get("Acidity", "").strip() or None,
            "country_code": row.get("Code", "").strip() or None,
            "country": row.get("Country", "").strip() or None,
            "region_id": int(row["RegionID"]) if row.get("RegionID") else None,
            "region_name": row.get("RegionName", "").strip() or None,
            "winery_id": int(row["WineryID"]) if row.get("WineryID") else None,
            "winery_name": row.get("WineryName", "").strip() or None,
            "website": row.get("Website", "").strip() or None,
            "vintages": row.get("Vintages", "").strip() or None,
            "avg_rating": None,
            "rating_count": 0,
        }
        wines.append(wine)

    return wines


def stream_aggregate_ratings(
    ratings_file: Path,
) -> dict[int, tuple[float, int]]:
    """Stream ratings CSV and aggregate sum/count per wine.

    Only keeps a running (sum, count) per wine ID in memory,
    not the full list of individual ratings.

    Args:
        ratings_file: Path to ratings CSV file

    Returns:
        Dict mapping wine_id -> (rating_sum, rating_count)
    """
    aggregated: dict[int, tuple[float, int]] = {}
    total_rows = 0

    with open(ratings_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            wine_id = int(row.get("WineID", 0))
            rating = float(row.get("Rating", 0))
            if wine_id in aggregated:
                prev_sum, prev_count = aggregated[wine_id]
                aggregated[wine_id] = (prev_sum + rating, prev_count + 1)
            else:
                aggregated[wine_id] = (rating, 1)
            total_rows += 1
            if total_rows % 1_000_000 == 0:
                print(f"  Processed {total_rows:,} ratings...", end="\r")

    print(f"  Processed {total_rows:,} ratings for {len(aggregated):,} wines")
    return aggregated


def parse_csv_ratings_small(csv_content: str) -> dict[int, tuple[float, int]]:
    """Parse ratings from string content (for small datasets like test).

    Args:
        csv_content: Raw CSV content as string

    Returns:
        Dict mapping wine_id -> (rating_sum, rating_count)
    """
    aggregated: dict[int, tuple[float, int]] = {}
    reader = csv.DictReader(io.StringIO(csv_content))

    for row in reader:
        wine_id = int(row.get("WineID", 0))
        rating = float(row.get("Rating", 0))
        if wine_id in aggregated:
            prev_sum, prev_count = aggregated[wine_id]
            aggregated[wine_id] = (prev_sum + rating, prev_count + 1)
        else:
            aggregated[wine_id] = (rating, 1)

    return aggregated


def get_mongodb_url() -> str:
    """Get MongoDB connection URL from environment or secrets.

    Returns:
        MongoDB connection URL
    """
    # Check environment variable first
    url = os.environ.get("WINEBOX_MONGODB_URL")
    if url:
        return url

    # Check secrets.env
    secrets_path = Path("/opt/winebox/secrets.env")
    if secrets_path.exists():
        for line in secrets_path.read_text().splitlines():
            if line.startswith("WINEBOX_MONGODB_URL="):
                return line.split("=", 1)[1].strip()

    return "mongodb://localhost:27017"


def import_to_mongodb(
    wines: list[dict[str, Any]],
    ratings_agg: dict[int, tuple[float, int]],
    version: str,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Import wines and ratings into MongoDB.

    Drops the xwines_wines collection and re-creates it from scratch.

    Args:
        wines: List of wine document dicts
        ratings_agg: Aggregated ratings: wine_id -> (sum, count)
        version: Dataset version name
        force: Re-import even if data exists
        dry_run: Preview without applying

    Returns:
        Exit code
    """
    mongo_url = get_mongodb_url()
    masked_url = mongo_url[:30] + "..." if len(mongo_url) > 30 else mongo_url
    print(f"Connecting to MongoDB: {masked_url}")

    client: MongoClient = MongoClient(mongo_url)
    db = client["winebox"]
    wines_col = db["xwines_wines"]
    metadata_col = db["xwines_metadata"]

    # Check existing import
    existing = {doc["key"]: doc["value"] for doc in metadata_col.find()}
    if existing and not force:
        print("X-Wines data already imported:")
        for key, value in existing.items():
            print(f"  {key}: {value}")
        print("\nUse --force to re-import")
        client.close()
        return 0

    if dry_run:
        print(f"[DRY RUN] Would drop xwines_wines and import {len(wines)} wines")
        client.close()
        return 0

    # Drop the collection entirely to ensure clean import
    print("Dropping xwines_wines collection...")
    wines_col.drop()
    metadata_col.drop()

    # Apply aggregated ratings to wine documents before insert
    total_rating_rows = 0
    if ratings_agg:
        print(f"Applying ratings to {len(ratings_agg):,} wines...")
        for wine in wines:
            agg = ratings_agg.get(wine["xwines_id"])
            if agg:
                rating_sum, rating_count = agg
                wine["avg_rating"] = round(rating_sum / rating_count, 2)
                wine["rating_count"] = rating_count
                total_rating_rows += rating_count

    # Bulk insert wines (insert_many is faster than upserts on a fresh collection)
    print(f"Inserting {len(wines):,} wines...")
    batch_size = 5000

    for i in range(0, len(wines), batch_size):
        batch = wines[i:i + batch_size]
        wines_col.insert_many(batch)
        done = min(i + batch_size, len(wines))
        print(f"  Inserted {done:,}/{len(wines):,} wines", end="\r")

    print(f"  Inserted {len(wines):,} wines                ")

    # Create indexes
    print("Creating indexes...")
    wines_col.create_index("xwines_id", unique=True)
    wines_col.create_index("name")
    wines_col.create_index("wine_type")
    wines_col.create_index("country_code")
    wines_col.create_index("winery_name")
    wines_col.create_index([("name", "text"), ("winery_name", "text")])
    print("  Indexes created")

    # Save metadata
    now = datetime.now(timezone.utc).isoformat()
    metadata_docs = [
        {"key": "version", "value": version, "updated_at": now},
        {"key": "source", "value": "https://github.com/rogerioxavier/X-Wines", "updated_at": now},
        {"key": "import_date", "value": now, "updated_at": now},
        {"key": "wine_count", "value": str(len(wines)), "updated_at": now},
        {"key": "rating_count", "value": str(total_rating_rows), "updated_at": now},
    ]
    metadata_col.insert_many(metadata_docs)

    client.close()

    print(f"\nImport complete!")
    print(f"  Wines: {len(wines):,}")
    print(f"  Ratings processed: {total_rating_rows:,}")
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Import X-Wines dataset into MongoDB",
    )
    parser.add_argument(
        "--version", choices=["test", "slim", "full"], default="test",
        help="Dataset version (default: test)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without importing")
    parser.add_argument("--skip-ratings", action="store_true", help="Import wines only")
    parser.add_argument("--force", action="store_true", help="Re-import even if data exists")

    args = parser.parse_args()
    signal.signal(signal.SIGINT, signal_handler)

    dataset = DATASET_VERSIONS[args.version]
    print(f"\nX-Wines MongoDB Import")
    print("=" * 50)
    print(f"Version: {args.version} - {dataset['description']}")
    print()

    try:
        # Load wine data
        if args.version == "test":
            wines_csv = download_csv(dataset["wines_url"], "wines CSV")
            wines = parse_csv_wines(wines_csv)
            ratings_agg: dict[int, tuple[float, int]] = {}
            if not args.skip_ratings:
                ratings_csv = download_csv(dataset["ratings_url"], "ratings CSV")
                ratings_agg = parse_csv_ratings_small(ratings_csv)
        else:
            if args.version == "slim":
                wines_file = DATA_DIR / "XWines_Slim_1K_wines.csv"
                ratings_file = DATA_DIR / "XWines_Slim_150K_ratings.csv"
            else:
                wines_file = DATA_DIR / "XWines_Full_100K_wines.csv"
                ratings_file = DATA_DIR / "XWines_Full_21M_ratings.csv"

            if not wines_file.exists():
                print(f"Error: {wines_file} not found")
                return 1

            print(f"Reading wines from {wines_file}...")
            with open(wines_file, encoding="utf-8") as f:
                wines = parse_csv_wines(f.read())

            ratings_agg = {}
            if not args.skip_ratings and ratings_file.exists():
                print(f"Streaming ratings from {ratings_file}...")
                ratings_agg = stream_aggregate_ratings(ratings_file)
            elif not args.skip_ratings:
                print(f"Warning: {ratings_file} not found, skipping ratings")

        return import_to_mongodb(
            wines=wines,
            ratings_agg=ratings_agg,
            version=args.version,
            force=args.force,
            dry_run=args.dry_run,
        )

    except ImportInterrupted:
        print("\n\nImport interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
