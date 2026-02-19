#!/usr/bin/env python3
"""Migration: Add email verification field to users table.

This migration adds:
- is_verified column to users table
- All existing users are set to verified=TRUE (grandfathered in)
- New registrations will default to verified=FALSE

Version: 3 -> 4
"""

import sqlite3

# Migration metadata
SOURCE_VERSION = 3
TARGET_VERSION = 4
DESCRIPTION = "Add is_verified field to users table for email verification"


def migrate(cursor: sqlite3.Cursor) -> None:
    """Apply the forward migration.

    Adds is_verified column to users table with existing users marked as verified.
    """
    # Check if column already exists
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    if "is_verified" not in columns:
        # Add is_verified column with default FALSE for new users
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT FALSE
        """)

        # Mark all existing users as verified (grandfathered in)
        cursor.execute("""
            UPDATE users SET is_verified = TRUE
        """)

        print("Added is_verified column to users table")
        print("Marked all existing users as verified")
    else:
        print("is_verified column already exists, skipping")


def validate(cursor: sqlite3.Cursor) -> bool:
    """Validate the migration was successful.

    Returns True if the is_verified column exists.
    """
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    if "is_verified" not in columns:
        print("Column is_verified not found in users table")
        return False

    return True
