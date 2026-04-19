#!/usr/bin/env python3
"""Import Kaggle wine price CSV files into MongoDB.

Reads Red.csv, White.csv, Rose.csv, and Sparkling.csv from a configurable
directory and imports them into the `kaggle_wine_prices` collection.

Uses pymongo directly (not the ODM) following the pattern of
scripts/annotate_xwines_prices.py.

Usage:
    uv run python scripts/import_kaggle_prices.py [OPTIONS]

Examples:
    uv run python scripts/import_kaggle_prices.py --dry-run
    uv run python scripts/import_kaggle_prices.py --path /tmp/wine-prices/
    uv run python scripts/import_kaggle_prices.py --database winebox_oat
    uv run python scripts/import_kaggle_prices.py --status
    uv run python scripts/import_kaggle_prices.py --reset
"""

import argparse
import csv
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient, UpdateOne

logger = logging.getLogger(__name__)

# Map CSV filenames to wine_type values
WINE_FILES: dict[str, str] = {
    "Red.csv": "red",
    "White.csv": "white",
    "Rose.csv": "rose",
    "Sparkling.csv": "sparkling",
}

COLLECTION_NAME = "kaggle_wine_prices"
BATCH_SIZE = 500  # Documents per bulk write


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


def parse_price(raw: str) -> float | None:
    """Parse a price string into a float, stripping currency symbols.

    Args:
        raw: Raw price string from CSV (e.g. "$12.99", "12.99", "").

    Returns:
        Price as float, or None if unparseable.
    """
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip().replace("$", "").replace(",", "").replace("\u20ac", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_vintage(raw: str) -> int | None:
    """Parse a vintage year string into an int.

    Args:
        raw: Raw year string from CSV (e.g. "2020", "N.V.", "").

    Returns:
        Vintage year as int, or None for non-vintage / unparseable.
    """
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip()
    if cleaned.upper() in ("N.V.", "NV", "N/A", "NA", ""):
        return None
    try:
        year = int(cleaned)
        # Sanity check: wine vintages should be reasonable years
        if 1800 <= year <= 2100:
            return year
        return None
    except ValueError:
        return None


def parse_float(raw: str) -> float | None:
    """Parse a string into a float, returning None on failure.

    Args:
        raw: Raw string from CSV.

    Returns:
        Float value, or None.
    """
    if not raw or not raw.strip():
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def parse_int(raw: str) -> int | None:
    """Parse a string into an int, returning None on failure.

    Args:
        raw: Raw string from CSV.

    Returns:
        Int value, or None.
    """
    if not raw or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def normalize_row(row: dict[str, str], wine_type: str) -> dict[str, Any] | None:
    """Normalize a CSV row into a MongoDB document.

    Args:
        row: Dict from csv.DictReader with CSV column names.
        wine_type: One of 'red', 'white', 'rose', 'sparkling'.

    Returns:
        Normalized document dict, or None if row is invalid.
    """
    name = (row.get("Name") or "").strip()
    if not name:
        return None

    winery = (row.get("Winery") or "").strip()
    country = (row.get("Country") or "").strip()
    region = (row.get("Region") or "").strip()
    rating = parse_float(row.get("Rating", ""))
    rating_count = parse_int(row.get("NumberOfRatings", ""))
    price_usd = parse_price(row.get("Price", ""))
    vintage = parse_vintage(row.get("Year", ""))

    # Skip rows with no useful price data
    if price_usd is None:
        return None

    return {
        "name": name,
        "name_lower": name.lower(),
        "winery": winery,
        "winery_lower": winery.lower(),
        "country": country,
        "region": region,
        "wine_type": wine_type,
        "rating": rating,
        "rating_count": rating_count,
        "price_usd": price_usd,
        "vintage": vintage,
        "imported_at": datetime.now(timezone.utc),
    }


def process_csv_file(
    filepath: Path,
    wine_type: str,
    collection: Any,
    *,
    dry_run: bool = False,
    shutdown_flag: list[bool],
) -> dict[str, int]:
    """Process a single CSV file and upsert rows into MongoDB.

    Args:
        filepath: Path to the CSV file.
        wine_type: Wine type string for this file.
        collection: PyMongo collection object.
        dry_run: If True, parse but don't write to DB.
        shutdown_flag: Mutable list with single bool for shutdown detection.

    Returns:
        Dict with stats: total_rows, valid_rows, skipped_rows, upserted, modified.
    """
    stats: dict[str, int] = {
        "total_rows": 0,
        "valid_rows": 0,
        "skipped_rows": 0,
        "upserted": 0,
        "modified": 0,
    }

    if not filepath.exists():
        print(f"  WARNING: {filepath} not found, skipping")
        return stats

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        batch: list[UpdateOne] = []

        for row in reader:
            if shutdown_flag[0]:
                print("\n  Shutdown requested, stopping file processing...")
                break

            stats["total_rows"] += 1
            doc = normalize_row(row, wine_type)

            if doc is None:
                stats["skipped_rows"] += 1
                continue

            stats["valid_rows"] += 1

            if not dry_run:
                # Upsert on (name_lower, winery_lower, vintage) for idempotency
                batch.append(
                    UpdateOne(
                        {
                            "name_lower": doc["name_lower"],
                            "winery_lower": doc["winery_lower"],
                            "vintage": doc["vintage"],
                        },
                        {"$set": doc},
                        upsert=True,
                    )
                )

                if len(batch) >= BATCH_SIZE:
                    result = collection.bulk_write(batch, ordered=False)
                    stats["upserted"] += result.upserted_count
                    stats["modified"] += result.modified_count
                    batch.clear()

                    # Print inline progress
                    print(
                        f"\r  {wine_type}: {stats['valid_rows']:,} rows processed...",
                        end="",
                        flush=True,
                    )

        # Flush remaining batch
        if batch and not dry_run:
            result = collection.bulk_write(batch, ordered=False)
            stats["upserted"] += result.upserted_count
            stats["modified"] += result.modified_count

    return stats


def ensure_indexes(collection: Any) -> None:
    """Create indexes on the kaggle_wine_prices collection.

    Args:
        collection: PyMongo collection object.
    """
    # Matching index for lookups by winery + name
    collection.create_index(
        [("winery_lower", 1), ("name_lower", 1)],
        name="idx_winery_name_lower",
    )
    # Geographic browsing index
    collection.create_index(
        [("country", 1), ("region", 1)],
        name="idx_country_region",
    )
    # Upsert key index (unique)
    collection.create_index(
        [("name_lower", 1), ("winery_lower", 1), ("vintage", 1)],
        unique=True,
        name="idx_upsert_key",
    )
    # Wine type for filtering
    collection.create_index("wine_type", name="idx_wine_type")

    print("Indexes created on kaggle_wine_prices")


def show_status(collection: Any, db_name: str) -> None:
    """Show collection status and summary statistics.

    Args:
        collection: PyMongo collection object.
        db_name: Database name for display.
    """
    total = collection.count_documents({})

    print(f"\nKaggle Wine Prices Status")
    print("=" * 50)
    print(f"Database: {db_name}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Total documents: {total:,}")

    if total == 0:
        return

    # Wine type breakdown
    print(f"\nBy wine type:")
    pipeline = [
        {"$group": {"_id": "$wine_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    for doc in collection.aggregate(pipeline):
        wine_type = doc["_id"] or "unknown"
        count = doc["count"]
        print(f"  {wine_type}: {count:,}")

    # Country breakdown (top 10)
    print(f"\nTop 10 countries:")
    pipeline = [
        {"$group": {"_id": "$country", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    for doc in collection.aggregate(pipeline):
        country = doc["_id"] or "unknown"
        count = doc["count"]
        print(f"  {country}: {count:,}")

    # Price statistics
    print(f"\nPrice statistics (USD):")
    pipeline = [
        {
            "$group": {
                "_id": None,
                "avg_price": {"$avg": "$price_usd"},
                "min_price": {"$min": "$price_usd"},
                "max_price": {"$max": "$price_usd"},
                "with_vintage": {
                    "$sum": {"$cond": [{"$ne": ["$vintage", None]}, 1, 0]}
                },
                "without_vintage": {
                    "$sum": {"$cond": [{"$eq": ["$vintage", None]}, 1, 0]}
                },
            }
        }
    ]
    for doc in collection.aggregate(pipeline):
        print(f"  Min:  ${doc['min_price']:.2f}")
        print(f"  Avg:  ${doc['avg_price']:.2f}")
        print(f"  Max:  ${doc['max_price']:.2f}")
        print(f"  With vintage: {doc['with_vintage']:,}")
        print(f"  Without vintage (N.V.): {doc['without_vintage']:,}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Import Kaggle wine price CSV files into MongoDB",
    )
    parser.add_argument(
        "--path",
        type=str,
        default="/tmp/wine-prices/",
        help="Directory containing CSV files (default: /tmp/wine-prices/)",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Override MongoDB database name (default: winebox_oat)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse files but don't write to database",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show collection status and exit",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop the collection and start fresh",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
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

    # MongoDB setup
    mongo_url = get_mongodb_url()
    db_name = args.database or os.environ.get("WINEBOX_DATABASE", "winebox_oat")
    client: MongoClient = MongoClient(mongo_url)
    db = client[db_name]
    collection = db[COLLECTION_NAME]

    # Shutdown flag (mutable list so inner functions can see changes)
    shutdown_flag: list[bool] = [False]

    def signal_handler(signum: int, frame: Any) -> None:
        print("\n\nShutting down gracefully...")
        shutdown_flag[0] = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # --status mode
        if args.status:
            show_status(collection, db_name)
            return 0

        # --reset mode
        if args.reset:
            count = collection.count_documents({})
            if count == 0:
                print("No data to delete.")
                return 0
            print(f"Dropping {COLLECTION_NAME} ({count:,} documents)...")
            collection.drop()
            print("Done. Collection dropped.")
            return 0

        # Import mode
        csv_dir = Path(args.path)
        if not csv_dir.is_dir():
            print(f"ERROR: Directory not found: {csv_dir}")
            return 1

        # Check which files exist
        found_files: list[tuple[str, str]] = []
        for filename, wine_type in WINE_FILES.items():
            filepath = csv_dir / filename
            if filepath.exists():
                found_files.append((filename, wine_type))
            else:
                print(f"WARNING: {filepath} not found, will skip")

        if not found_files:
            print(f"ERROR: No CSV files found in {csv_dir}")
            return 1

        print(f"\nKaggle Wine Price Import")
        print("=" * 50)
        print(f"Database: {db_name}")
        print(f"Collection: {COLLECTION_NAME}")
        print(f"Source directory: {csv_dir}")
        print(f"Files found: {', '.join(f for f, _ in found_files)}")
        if args.dry_run:
            print("Mode: DRY RUN (no database writes)")
        print()

        # Ensure indexes before import
        if not args.dry_run:
            ensure_indexes(collection)
            print()

        # Process each file
        total_stats: dict[str, int] = {
            "total_rows": 0,
            "valid_rows": 0,
            "skipped_rows": 0,
            "upserted": 0,
            "modified": 0,
        }

        start_time = time.monotonic()

        for filename, wine_type in found_files:
            if shutdown_flag[0]:
                break

            filepath = csv_dir / filename
            print(f"Processing {filename} ({wine_type})...")

            file_stats = process_csv_file(
                filepath,
                wine_type,
                collection,
                dry_run=args.dry_run,
                shutdown_flag=shutdown_flag,
            )

            # Clear the inline progress line
            print(f"\r  {wine_type}: done                              ")

            # Accumulate stats
            for key in total_stats:
                total_stats[key] += file_stats[key]

            # Per-file summary
            print(f"  Total rows:   {file_stats['total_rows']:,}")
            print(f"  Valid rows:   {file_stats['valid_rows']:,}")
            print(f"  Skipped:      {file_stats['skipped_rows']:,}")
            if not args.dry_run:
                print(f"  Upserted:     {file_stats['upserted']:,}")
                print(f"  Modified:     {file_stats['modified']:,}")
            print()

        elapsed = time.monotonic() - start_time

        # Summary
        print("=" * 50)
        print(f"Import Summary")
        print("=" * 50)
        print(f"Total rows read:    {total_stats['total_rows']:,}")
        print(f"Valid rows:         {total_stats['valid_rows']:,}")
        print(f"Skipped rows:       {total_stats['skipped_rows']:,}")
        if not args.dry_run:
            print(f"Upserted (new):     {total_stats['upserted']:,}")
            print(f"Modified (updated): {total_stats['modified']:,}")
        print(f"Time elapsed:       {elapsed:.1f}s")

        # Show final collection count
        if not args.dry_run:
            final_count = collection.count_documents({})
            print(f"Collection total:   {final_count:,} documents")

        if shutdown_flag[0]:
            print("\nImport was interrupted. Re-run to continue (upserts are idempotent).")

        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        return 130
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=args.verbose)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
