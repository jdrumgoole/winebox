#!/usr/bin/env python3
"""Revert migration: Remove full_name and anthropic_api_key columns from users table.

This revert removes the user settings columns added in version 1.
WARNING: Data in these columns will be lost!

Version: 1 -> 0
"""

import sqlite3

# Migration metadata
SOURCE_VERSION = 1
TARGET_VERSION = 0
DESCRIPTION = "Remove full_name and anthropic_api_key from users table"


def migrate(cursor: sqlite3.Cursor) -> None:
    """Apply the reverse migration (revert).

    Removes full_name and anthropic_api_key columns from the users table.

    Since SQLite doesn't support DROP COLUMN in older versions, we use
    the table rebuild pattern:
    1. Create new table without the columns
    2. Copy data from old table
    3. Drop old table
    4. Rename new table
    5. Recreate indexes

    WARNING: Data in full_name and anthropic_api_key columns will be lost!
    """
    # Check if columns exist (may have already been removed)
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    if "full_name" not in columns and "anthropic_api_key" not in columns:
        # Columns already removed, nothing to do
        return

    # Disable foreign key checks during table rebuild
    cursor.execute("PRAGMA foreign_keys = OFF")

    try:
        # 1. Create new table without full_name and anthropic_api_key
        cursor.execute("""
            CREATE TABLE users_new (
                id CHAR(36) PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                email VARCHAR(255) UNIQUE,
                hashed_password VARCHAR(255) NOT NULL,
                is_active BOOLEAN DEFAULT 1 NOT NULL,
                is_admin BOOLEAN DEFAULT 0 NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                last_login DATETIME
            )
        """)

        # 2. Copy data from old table (excluding removed columns)
        cursor.execute("""
            INSERT INTO users_new (
                id, username, email, hashed_password,
                is_active, is_admin, created_at, updated_at, last_login
            )
            SELECT
                id, username, email, hashed_password,
                is_active, is_admin, created_at, updated_at, last_login
            FROM users
        """)

        # 3. Drop old table
        cursor.execute("DROP TABLE users")

        # 4. Rename new table
        cursor.execute("ALTER TABLE users_new RENAME TO users")

        # 5. Recreate indexes
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"
        )

    finally:
        # Re-enable foreign key checks
        cursor.execute("PRAGMA foreign_keys = ON")


def validate(cursor: sqlite3.Cursor) -> bool:
    """Validate the revert was successful.

    Returns True if both columns have been removed from the users table.
    """
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    # Verify columns are removed
    if "full_name" in columns or "anthropic_api_key" in columns:
        return False

    # Verify essential columns still exist
    required_columns = {
        "id", "username", "email", "hashed_password",
        "is_active", "is_admin", "created_at", "updated_at", "last_login"
    }
    return required_columns.issubset(columns)
