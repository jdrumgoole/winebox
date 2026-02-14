#!/usr/bin/env python3
"""Migration: Add X-Wines dataset tables.

This migration adds:
- xwines_wines table (external wine reference data from X-Wines dataset)
- xwines_metadata table (dataset version tracking)

Note: xwines_ratings table is optional and can be added later for recommendations.

Version: 2 -> 3
"""

import sqlite3

# Migration metadata
SOURCE_VERSION = 2
TARGET_VERSION = 3
DESCRIPTION = "Add X-Wines dataset tables for wine autocomplete and reference data"


def migrate(cursor: sqlite3.Cursor) -> None:
    """Apply the forward migration.

    Creates X-Wines reference tables for wine autocomplete and auto-fill.
    """
    # 1. Create xwines_wines table - external wine reference data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS xwines_wines (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            wine_type TEXT NOT NULL,
            elaborate TEXT,
            grapes TEXT,
            harmonize TEXT,
            abv REAL,
            body TEXT,
            acidity TEXT,
            country_code TEXT,
            country TEXT,
            region_id INTEGER,
            region_name TEXT,
            winery_id INTEGER,
            winery_name TEXT,
            website TEXT,
            vintages TEXT,
            avg_rating REAL,
            rating_count INTEGER DEFAULT 0
        )
    """)

    # Create indexes for efficient searching
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_xwines_name ON xwines_wines(name)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_xwines_winery ON xwines_wines(winery_name)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_xwines_country ON xwines_wines(country_code)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_xwines_type ON xwines_wines(wine_type)"
    )

    # 2. Create xwines_metadata table - dataset version tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS xwines_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def validate(cursor: sqlite3.Cursor) -> bool:
    """Validate the migration was successful.

    Returns True if all tables exist.
    """
    # Check tables exist
    tables_to_check = [
        "xwines_wines",
        "xwines_metadata",
    ]

    for table in tables_to_check:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if not cursor.fetchone():
            print(f"Table {table} not found")
            return False

    # Check xwines_wines table has required columns
    cursor.execute("PRAGMA table_info(xwines_wines)")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = [
        "id",
        "name",
        "wine_type",
        "grapes",
        "abv",
        "body",
        "country",
        "region_name",
        "winery_name",
        "avg_rating",
        "rating_count",
    ]

    for col in required_columns:
        if col not in columns:
            print(f"Column {col} not found in xwines_wines table")
            return False

    return True
