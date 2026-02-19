#!/usr/bin/env python3
"""Revert Migration: Remove wine taxonomy tables and wine table extensions.

This reverts:
- wine_types table
- grape_varieties table
- regions table
- classifications table
- wine_grapes table
- wine_scores table
- New columns on wines table for taxonomy

WARNING: This will delete all data in the taxonomy tables!

Version: 2 -> 1
"""

import sqlite3

# Migration metadata
SOURCE_VERSION = 2
TARGET_VERSION = 1
DESCRIPTION = "Remove wine taxonomy tables and wine table extensions"


def migrate(cursor: sqlite3.Cursor) -> None:
    """Apply the revert migration.

    Removes taxonomy tables and columns from wines table.
    Note: SQLite doesn't support DROP COLUMN, so we recreate the wines table.
    """
    # 1. Drop junction and score tables first (they have foreign keys)
    cursor.execute("DROP TABLE IF EXISTS wine_grapes")
    cursor.execute("DROP TABLE IF EXISTS wine_scores")

    # 2. Drop reference tables
    cursor.execute("DROP TABLE IF EXISTS wine_types")
    cursor.execute("DROP TABLE IF EXISTS grape_varieties")
    cursor.execute("DROP TABLE IF EXISTS classifications")
    cursor.execute("DROP TABLE IF EXISTS regions")

    # 3. Remove columns from wines table
    # SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
    # This preserves all existing data in the original columns

    # Get current data
    cursor.execute("""
        SELECT id, name, winery, vintage, grape_variety, region, country,
               alcohol_percentage, front_label_text, back_label_text,
               front_label_image_path, back_label_image_path, created_at, updated_at
        FROM wines
    """)
    wines_data = cursor.fetchall()

    # Drop existing table
    cursor.execute("DROP TABLE IF EXISTS wines")

    # Recreate wines table without taxonomy columns
    cursor.execute("""
        CREATE TABLE wines (
            id CHAR(36) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            winery VARCHAR(255),
            vintage INTEGER,
            grape_variety VARCHAR(255),
            region VARCHAR(255),
            country VARCHAR(255),
            alcohol_percentage REAL,
            front_label_text TEXT NOT NULL DEFAULT '',
            back_label_text TEXT,
            front_label_image_path VARCHAR(512) NOT NULL,
            back_label_image_path VARCHAR(512),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    """)

    # Recreate indexes
    cursor.execute("CREATE INDEX ix_wines_name ON wines(name)")
    cursor.execute("CREATE INDEX ix_wines_winery ON wines(winery)")
    cursor.execute("CREATE INDEX ix_wines_vintage ON wines(vintage)")
    cursor.execute("CREATE INDEX ix_wines_grape_variety ON wines(grape_variety)")
    cursor.execute("CREATE INDEX ix_wines_region ON wines(region)")
    cursor.execute("CREATE INDEX ix_wines_country ON wines(country)")

    # Restore data
    for row in wines_data:
        cursor.execute("""
            INSERT INTO wines (id, name, winery, vintage, grape_variety, region, country,
                              alcohol_percentage, front_label_text, back_label_text,
                              front_label_image_path, back_label_image_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row)


def validate(cursor: sqlite3.Cursor) -> bool:
    """Validate the revert was successful.

    Returns True if taxonomy tables are removed and wines table is intact.
    """
    # Check taxonomy tables are gone
    tables_to_check = [
        "wine_types",
        "grape_varieties",
        "regions",
        "classifications",
        "wine_grapes",
        "wine_scores",
    ]

    for table in tables_to_check:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if cursor.fetchone():
            print(f"Table {table} still exists")
            return False

    # Check wines table exists and has original columns
    cursor.execute("PRAGMA table_info(wines)")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = ["id", "name", "winery", "vintage", "grape_variety", "region", "country"]
    for col in required_columns:
        if col not in columns:
            print(f"Column {col} not found in wines table")
            return False

    # Ensure taxonomy columns are gone
    removed_columns = [
        "wine_type_id",
        "wine_subtype",
        "appellation_id",
        "classification_id",
        "price_tier",
        "drink_window_start",
        "drink_window_end",
        "producer_type",
    ]
    for col in removed_columns:
        if col in columns:
            print(f"Column {col} should have been removed from wines table")
            return False

    return True
