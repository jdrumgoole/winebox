#!/usr/bin/env python3
"""Migration: Add wine taxonomy tables and wine table extensions.

This migration adds:
- wine_types table (reference data)
- grape_varieties table (reference data)
- regions table (hierarchical reference data)
- classifications table (reference data)
- wine_grapes table (junction table for multi-grape blends)
- wine_scores table (ratings from various sources)
- New columns on wines table for taxonomy

Version: 1 -> 2
"""

import sqlite3

# Migration metadata
SOURCE_VERSION = 1
TARGET_VERSION = 2
DESCRIPTION = "Add wine taxonomy tables and wine table extensions"


def migrate(cursor: sqlite3.Cursor) -> None:
    """Apply the forward migration.

    Creates new reference tables and adds taxonomy columns to wines table.
    """
    # 1. Create wine_types table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wine_types (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT
        )
    """)

    # 2. Create grape_varieties table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grape_varieties (
            id CHAR(36) PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL,
            category TEXT,
            origin_country TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_grape_varieties_name ON grape_varieties(name)")

    # 3. Create regions table (hierarchical, self-referential)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            id CHAR(36) PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            parent_id CHAR(36),
            country TEXT,
            level INTEGER NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES regions(id) ON DELETE SET NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_regions_name ON regions(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_regions_parent_id ON regions(parent_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_regions_country ON regions(country)")

    # 4. Create classifications table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS classifications (
            id CHAR(36) PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            country TEXT NOT NULL,
            system TEXT NOT NULL,
            level INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_classifications_name ON classifications(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_classifications_country ON classifications(country)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_classifications_system ON classifications(system)")

    # 5. Create wine_grapes junction table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wine_grapes (
            id CHAR(36) PRIMARY KEY,
            wine_id CHAR(36) NOT NULL,
            grape_variety_id CHAR(36) NOT NULL,
            percentage REAL,
            FOREIGN KEY (wine_id) REFERENCES wines(id) ON DELETE CASCADE,
            FOREIGN KEY (grape_variety_id) REFERENCES grape_varieties(id) ON DELETE CASCADE,
            UNIQUE(wine_id, grape_variety_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_wine_grapes_wine_id ON wine_grapes(wine_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_wine_grapes_grape_variety_id ON wine_grapes(grape_variety_id)")

    # 6. Create wine_scores table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wine_scores (
            id CHAR(36) PRIMARY KEY,
            wine_id CHAR(36) NOT NULL,
            source TEXT NOT NULL,
            score INTEGER NOT NULL,
            score_type TEXT NOT NULL,
            review_date DATE,
            reviewer TEXT,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            FOREIGN KEY (wine_id) REFERENCES wines(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_wine_scores_wine_id ON wine_scores(wine_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_wine_scores_source ON wine_scores(source)")

    # 7. Add new columns to wines table
    # Check existing columns first
    cursor.execute("PRAGMA table_info(wines)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("wine_type_id", "TEXT REFERENCES wine_types(id) ON DELETE SET NULL"),
        ("wine_subtype", "TEXT"),
        ("appellation_id", "CHAR(36) REFERENCES regions(id) ON DELETE SET NULL"),
        ("classification_id", "CHAR(36) REFERENCES classifications(id) ON DELETE SET NULL"),
        ("price_tier", "TEXT"),
        ("drink_window_start", "INTEGER"),
        ("drink_window_end", "INTEGER"),
        ("producer_type", "TEXT"),
    ]

    for column_name, column_def in new_columns:
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE wines ADD COLUMN {column_name} {column_def}")

    # Create indexes for new columns
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_wines_wine_type_id ON wines(wine_type_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_wines_appellation_id ON wines(appellation_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_wines_classification_id ON wines(classification_id)")


def validate(cursor: sqlite3.Cursor) -> bool:
    """Validate the migration was successful.

    Returns True if all tables and columns exist.
    """
    # Check tables exist
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
        if not cursor.fetchone():
            print(f"Table {table} not found")
            return False

    # Check wines table has new columns
    cursor.execute("PRAGMA table_info(wines)")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = [
        "wine_type_id",
        "wine_subtype",
        "appellation_id",
        "classification_id",
        "price_tier",
        "drink_window_start",
        "drink_window_end",
        "producer_type",
    ]

    for col in required_columns:
        if col not in columns:
            print(f"Column {col} not found in wines table")
            return False

    return True
