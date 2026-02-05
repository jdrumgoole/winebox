#!/usr/bin/env python3
"""Migration: Add full_name and anthropic_api_key columns to users table.

This migration adds user settings columns:
- full_name: Optional display name for the user
- anthropic_api_key: Optional API key for Claude Vision (per-user override)

Version: 0 -> 1
"""

import sqlite3

# Migration metadata
SOURCE_VERSION = 0
TARGET_VERSION = 1
DESCRIPTION = "Add full_name and anthropic_api_key to users table"


def migrate(cursor: sqlite3.Cursor) -> None:
    """Apply the forward migration.

    Adds full_name and anthropic_api_key columns to the users table.
    These are nullable columns, so existing users will have NULL values.
    """
    # Check existing columns
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    # Add full_name column if it doesn't exist
    if "full_name" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN full_name VARCHAR(255)")

    # Add anthropic_api_key column if it doesn't exist
    if "anthropic_api_key" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN anthropic_api_key VARCHAR(255)")


def validate(cursor: sqlite3.Cursor) -> bool:
    """Validate the migration was successful.

    Returns True if both columns exist in the users table.
    """
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    return "full_name" in columns and "anthropic_api_key" in columns
