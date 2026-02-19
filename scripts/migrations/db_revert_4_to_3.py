#!/usr/bin/env python3
"""Revert Migration: Remove email verification field from users table.

This migration removes:
- is_verified column from users table

Note: SQLite does not support DROP COLUMN directly, so this creates a new
table without the column and copies data over.

Version: 4 -> 3
"""

import sqlite3

# Migration metadata
SOURCE_VERSION = 4
TARGET_VERSION = 3
DESCRIPTION = "Remove is_verified field from users table"


def migrate(cursor: sqlite3.Cursor) -> None:
    """Apply the revert migration.

    Removes is_verified column from users table.
    """
    # Check if column exists
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    if "is_verified" not in columns:
        print("is_verified column does not exist, skipping")
        return

    # SQLite doesn't support DROP COLUMN, so we need to recreate the table
    # 1. Create new table without is_verified
    cursor.execute("""
        CREATE TABLE users_new (
            id CHAR(36) PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            email VARCHAR(255) UNIQUE,
            full_name VARCHAR(255),
            hashed_password VARCHAR(255) NOT NULL,
            anthropic_api_key VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            last_login TIMESTAMP
        )
    """)

    # 2. Copy data (excluding is_verified)
    cursor.execute("""
        INSERT INTO users_new (
            id, username, email, full_name, hashed_password, anthropic_api_key,
            is_active, is_admin, created_at, updated_at, last_login
        )
        SELECT
            id, username, email, full_name, hashed_password, anthropic_api_key,
            is_active, is_admin, created_at, updated_at, last_login
        FROM users
    """)

    # 3. Drop old table
    cursor.execute("DROP TABLE users")

    # 4. Rename new table
    cursor.execute("ALTER TABLE users_new RENAME TO users")

    # 5. Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_users_username ON users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_users_email ON users(email)")

    print("Removed is_verified column from users table")


def validate(cursor: sqlite3.Cursor) -> bool:
    """Validate the revert was successful.

    Returns True if the is_verified column does not exist.
    """
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    if "is_verified" in columns:
        print("Column is_verified still exists in users table")
        return False

    # Verify essential columns exist
    required = ["id", "username", "email", "hashed_password", "is_active", "is_admin"]
    for col in required:
        if col not in columns:
            print(f"Required column {col} not found in users table")
            return False

    return True
