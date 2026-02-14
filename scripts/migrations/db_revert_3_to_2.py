#!/usr/bin/env python3
"""Revert migration: Remove X-Wines dataset tables.

This revert removes:
- xwines_wines table
- xwines_metadata table

Version: 3 -> 2
"""

import sqlite3

# Migration metadata
SOURCE_VERSION = 3
TARGET_VERSION = 2
DESCRIPTION = "Remove X-Wines dataset tables"


def migrate(cursor: sqlite3.Cursor) -> None:
    """Apply the revert migration.

    Drops X-Wines related tables.
    """
    # Drop tables (indexes are dropped automatically)
    cursor.execute("DROP TABLE IF EXISTS xwines_wines")
    cursor.execute("DROP TABLE IF EXISTS xwines_metadata")


def validate(cursor: sqlite3.Cursor) -> bool:
    """Validate the revert was successful.

    Returns True if tables no longer exist.
    """
    tables_to_check = [
        "xwines_wines",
        "xwines_metadata",
    ]

    for table in tables_to_check:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if cursor.fetchone():
            print(f"Table {table} still exists after revert")
            return False

    return True
