#!/usr/bin/env python3
"""Import X-Wines dataset into WineBox database.

This script downloads and imports the X-Wines dataset which provides:
- 100,646 wines with 17 attributes
- 21,013,536 ratings (1-5 scale)
- 1,056,079 users
- 62 countries, 6 wine types

Dataset source: https://github.com/rogerioxavier/X-Wines

Usage:
    # Import test dataset (default for dev)
    uv run python -m scripts.import_xwines

    # Import slim dataset
    uv run python -m scripts.import_xwines --version slim

    # Import full dataset (production)
    uv run python -m scripts.import_xwines --version full

    # Options
    --database PATH     # Custom database path
    --dry-run           # Preview without importing
    --skip-ratings      # Import wines only (faster)
    --force             # Re-import even if data exists
"""

import argparse
import csv
import io
import json
import signal
import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

# Dataset URLs
GITHUB_BASE = "https://raw.githubusercontent.com/rogerioxavier/X-Wines/main/Dataset/last"

# Dataset versions with their URLs and expected counts
DATASET_VERSIONS = {
    "test": {
        "wines_url": f"{GITHUB_BASE}/XWines_Test_100_wines.csv",
        "ratings_url": f"{GITHUB_BASE}/XWines_Test_1K_ratings.csv",
        "expected_wines": 100,
        "expected_ratings": 1000,
        "description": "Test dataset (100 wines, 1K ratings)",
    },
    "slim": {
        # Slim dataset is in a zip file on Google Drive
        "wines_url": None,  # Not directly downloadable
        "ratings_url": None,
        "expected_wines": 1007,
        "expected_ratings": 150000,
        "description": "Slim dataset (1,007 wines, 150K ratings) - requires manual download",
    },
    "full": {
        # Full dataset is in a zip file on Google Drive
        "wines_url": None,  # Not directly downloadable
        "ratings_url": None,
        "expected_wines": 100646,
        "expected_ratings": 21013536,
        "description": "Full dataset (100K wines, 21M ratings) - requires manual download",
    },
}

# Default database path
DEFAULT_DB_PATH = Path("data/winebox.db")


class ImportInterrupted(Exception):
    """Raised when import is interrupted by Ctrl+C."""

    pass


def signal_handler(signum: int, frame: Any) -> None:
    """Handle Ctrl+C gracefully."""
    raise ImportInterrupted()


def download_csv(url: str, description: str = "data") -> str:
    """Download CSV file from URL with progress indication.

    Args:
        url: URL to download from
        description: Description for progress messages

    Returns:
        CSV content as string

    Raises:
        HTTPError: If download fails
        URLError: If connection fails
    """
    print(f"Downloading {description}...")
    print(f"  URL: {url}")

    try:
        with urlopen(url, timeout=60) as response:
            total_size = response.headers.get("content-length")
            if total_size:
                total_size = int(total_size)
                print(f"  Size: {total_size / 1024:.1f} KB")

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
    """Parse wines CSV content into list of dictionaries.

    Args:
        csv_content: Raw CSV content as string

    Returns:
        List of wine dictionaries
    """
    wines = []
    reader = csv.DictReader(io.StringIO(csv_content))

    for row in reader:
        wine = {
            "id": int(row.get("WineID", 0)),
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
        }
        wines.append(wine)

    return wines


def parse_csv_ratings(csv_content: str) -> dict[int, list[float]]:
    """Parse ratings CSV and aggregate by wine ID.

    Args:
        csv_content: Raw CSV content as string

    Returns:
        Dictionary mapping wine_id to list of ratings
    """
    ratings_by_wine: dict[int, list[float]] = {}
    reader = csv.DictReader(io.StringIO(csv_content))

    for row in reader:
        wine_id = int(row.get("WineID", 0))
        rating = float(row.get("Rating", 0))

        if wine_id not in ratings_by_wine:
            ratings_by_wine[wine_id] = []
        ratings_by_wine[wine_id].append(rating)

    return ratings_by_wine


def check_existing_import(cursor: sqlite3.Cursor) -> dict[str, str] | None:
    """Check if X-Wines data has already been imported.

    Args:
        cursor: Database cursor

    Returns:
        Metadata dict if already imported, None otherwise
    """
    try:
        cursor.execute("SELECT key, value FROM xwines_metadata")
        rows = cursor.fetchall()
        if rows:
            return {row[0]: row[1] for row in rows}
    except sqlite3.OperationalError:
        # Table doesn't exist
        pass
    return None


def import_wines(
    cursor: sqlite3.Cursor, wines: list[dict[str, Any]], batch_size: int = 1000
) -> int:
    """Import wines into database.

    Args:
        cursor: Database cursor
        wines: List of wine dictionaries
        batch_size: Number of wines to insert per batch

    Returns:
        Number of wines imported
    """
    print(f"Importing {len(wines)} wines...")

    insert_sql = """
        INSERT OR REPLACE INTO xwines_wines (
            id, name, wine_type, elaborate, grapes, harmonize,
            abv, body, acidity, country_code, country,
            region_id, region_name, winery_id, winery_name,
            website, vintages, avg_rating, rating_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    count = 0
    for i in range(0, len(wines), batch_size):
        batch = wines[i : i + batch_size]
        values = [
            (
                w["id"],
                w["name"],
                w["wine_type"],
                w["elaborate"],
                w["grapes"],
                w["harmonize"],
                w["abv"],
                w["body"],
                w["acidity"],
                w["country_code"],
                w["country"],
                w["region_id"],
                w["region_name"],
                w["winery_id"],
                w["winery_name"],
                w["website"],
                w["vintages"],
                None,  # avg_rating - will be updated later
                0,  # rating_count - will be updated later
            )
            for w in batch
        ]
        cursor.executemany(insert_sql, values)
        count += len(batch)
        print(f"  Imported {count}/{len(wines)} wines", end="\r")

    print(f"  Imported {count}/{len(wines)} wines")
    return count


def update_wine_ratings(
    cursor: sqlite3.Cursor, ratings_by_wine: dict[int, list[float]]
) -> int:
    """Update wine records with aggregated ratings.

    Args:
        cursor: Database cursor
        ratings_by_wine: Dictionary mapping wine_id to list of ratings

    Returns:
        Number of wines updated
    """
    print(f"Computing ratings for {len(ratings_by_wine)} wines...")

    update_sql = """
        UPDATE xwines_wines
        SET avg_rating = ?, rating_count = ?
        WHERE id = ?
    """

    count = 0
    for wine_id, ratings in ratings_by_wine.items():
        avg_rating = sum(ratings) / len(ratings)
        cursor.execute(update_sql, (round(avg_rating, 2), len(ratings), wine_id))
        count += 1
        if count % 1000 == 0:
            print(f"  Updated {count}/{len(ratings_by_wine)} wines", end="\r")

    print(f"  Updated {count}/{len(ratings_by_wine)} wines")
    return count


def save_metadata(
    cursor: sqlite3.Cursor, version: str, wine_count: int, rating_count: int
) -> None:
    """Save import metadata to database.

    Args:
        cursor: Database cursor
        version: Dataset version imported
        wine_count: Number of wines imported
        rating_count: Number of ratings processed
    """
    metadata = {
        "version": version,
        "source": "https://github.com/rogerioxavier/X-Wines",
        "import_date": datetime.now().isoformat(),
        "wine_count": str(wine_count),
        "rating_count": str(rating_count),
    }

    insert_sql = """
        INSERT OR REPLACE INTO xwines_metadata (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    """

    for key, value in metadata.items():
        cursor.execute(insert_sql, (key, value))


def clear_existing_data(cursor: sqlite3.Cursor) -> None:
    """Clear existing X-Wines data from database.

    Args:
        cursor: Database cursor
    """
    print("Clearing existing X-Wines data...")
    cursor.execute("DELETE FROM xwines_wines")
    cursor.execute("DELETE FROM xwines_metadata")


def main() -> int:
    """Main entry point for X-Wines import script.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parser = argparse.ArgumentParser(
        description="Import X-Wines dataset into WineBox database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Dataset versions:
  test   - 100 wines, 1K ratings (default, for development)
  slim   - 1,007 wines, 150K ratings (requires manual download)
  full   - 100K wines, 21M ratings (requires manual download)

For slim/full datasets, download from Google Drive and place CSV files in:
  data/xwines/XWines_Slim_1K_wines.csv
  data/xwines/XWines_Slim_150K_ratings.csv
  (or XWines_Full_100K_wines.csv / XWines_Full_21M_ratings.csv)
        """,
    )
    parser.add_argument(
        "--version",
        choices=["test", "slim", "full"],
        default="test",
        help="Dataset version to import (default: test)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without importing",
    )
    parser.add_argument(
        "--skip-ratings",
        action="store_true",
        help="Import wines only (faster)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-import even if data exists",
    )

    args = parser.parse_args()

    # Set up signal handler for graceful interruption
    signal.signal(signal.SIGINT, signal_handler)

    # Get dataset configuration
    dataset = DATASET_VERSIONS[args.version]
    print(f"\nX-Wines Dataset Import")
    print(f"=" * 50)
    print(f"Version: {args.version} - {dataset['description']}")
    print(f"Database: {args.database}")
    print()

    # Check database exists
    if not args.database.exists():
        print(f"Error: Database not found at {args.database}")
        print("Run migrations first: uv run python -m scripts.migrations.runner up")
        return 1

    try:
        # Connect to database
        conn = sqlite3.connect(args.database)
        cursor = conn.cursor()

        # Check if xwines_wines table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='xwines_wines'"
        )
        if not cursor.fetchone():
            print("Error: xwines_wines table not found")
            print("Run migrations first: uv run python -m scripts.migrations.runner up")
            conn.close()
            return 1

        # Check for existing import
        existing = check_existing_import(cursor)
        if existing and not args.force:
            print("X-Wines data already imported:")
            for key, value in existing.items():
                print(f"  {key}: {value}")
            print("\nUse --force to re-import")
            conn.close()
            return 0

        if args.dry_run:
            print("[DRY RUN] Would import:")
            print(f"  - {dataset['expected_wines']} wines")
            print(f"  - {dataset['expected_ratings']} ratings")
            conn.close()
            return 0

        # For test version, download from GitHub
        if args.version == "test":
            # Download wines CSV
            wines_csv = download_csv(dataset["wines_url"], "wines CSV")
            wines = parse_csv_wines(wines_csv)

            # Download ratings CSV (unless skipping)
            ratings_by_wine: dict[int, list[float]] = {}
            if not args.skip_ratings:
                ratings_csv = download_csv(dataset["ratings_url"], "ratings CSV")
                ratings_by_wine = parse_csv_ratings(ratings_csv)

        else:
            # For slim/full, look for local files
            data_dir = Path("data/xwines")
            if args.version == "slim":
                wines_file = data_dir / "XWines_Slim_1K_wines.csv"
                ratings_file = data_dir / "XWines_Slim_150K_ratings.csv"
            else:  # full
                wines_file = data_dir / "XWines_Full_100K_wines.csv"
                ratings_file = data_dir / "XWines_Full_21M_ratings.csv"

            if not wines_file.exists():
                print(f"Error: {wines_file} not found")
                print(f"\nFor {args.version} dataset, download from X-Wines repository:")
                print("  https://github.com/rogerioxavier/X-Wines")
                print(f"And place CSV files in: {data_dir}/")
                conn.close()
                return 1

            print(f"Reading wines from {wines_file}...")
            with open(wines_file, encoding="utf-8") as f:
                wines = parse_csv_wines(f.read())

            ratings_by_wine = {}
            if not args.skip_ratings and ratings_file.exists():
                print(f"Reading ratings from {ratings_file}...")
                with open(ratings_file, encoding="utf-8") as f:
                    ratings_by_wine = parse_csv_ratings(f.read())
            elif not args.skip_ratings:
                print(f"Warning: {ratings_file} not found, skipping ratings")

        # Clear existing data if re-importing
        if existing and args.force:
            clear_existing_data(cursor)

        # Import wines
        wine_count = import_wines(cursor, wines)

        # Update ratings
        rating_count = 0
        if ratings_by_wine:
            update_wine_ratings(cursor, ratings_by_wine)
            rating_count = sum(len(r) for r in ratings_by_wine.values())

        # Save metadata
        save_metadata(cursor, args.version, wine_count, rating_count)

        # Commit transaction
        conn.commit()
        conn.close()

        print()
        print(f"Import complete!")
        print(f"  Wines: {wine_count}")
        print(f"  Ratings processed: {rating_count}")

        return 0

    except ImportInterrupted:
        print("\n\nImport interrupted by user")
        if "conn" in locals():
            conn.rollback()
            conn.close()
        return 130  # Standard exit code for Ctrl+C

    except Exception as e:
        print(f"\nError: {e}")
        if "conn" in locals():
            conn.rollback()
            conn.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
