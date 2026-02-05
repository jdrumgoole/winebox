#!/usr/bin/env python3
"""Database migration runner for WineBox.

This module provides the main migration runner that handles:
- Schema version tracking via a schema_version table
- Forward migrations (up)
- Reverse migrations (down)
- Status reporting and history

Usage:
    uv run python -m scripts.migrations.runner status
    uv run python -m scripts.migrations.runner up [--to VERSION]
    uv run python -m scripts.migrations.runner down --to VERSION
    uv run python -m scripts.migrations.runner history
"""

import argparse
import importlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# Default database path
DEFAULT_DB_PATH = "data/winebox.db"

# Schema version table DDL
SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    migrate_script TEXT NOT NULL,
    revert_script TEXT NOT NULL,
    description TEXT NOT NULL,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)
"""


def get_db_path(db_path: str | None = None) -> str:
    """Get the database path, with fallback to default."""
    return db_path or DEFAULT_DB_PATH


def get_connection(db_path: str) -> sqlite3.Connection:
    """Get a database connection."""
    return sqlite3.connect(db_path)


def ensure_schema_version_table(cursor: sqlite3.Cursor) -> None:
    """Ensure the schema_version table exists."""
    cursor.execute(SCHEMA_VERSION_DDL)


def get_current_version(cursor: sqlite3.Cursor) -> int:
    """Get the current schema version from the database.

    Returns 0 if no migrations have been applied.
    """
    # Check if schema_version table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    if not cursor.fetchone():
        return 0

    # Get max version
    cursor.execute("SELECT MAX(version) FROM schema_version")
    result = cursor.fetchone()
    return result[0] if result[0] is not None else 0


def get_table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    """Get column names for a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def detect_current_state(cursor: sqlite3.Cursor) -> int:
    """Detect the current database state based on schema.

    This is used to bootstrap the schema_version table for existing databases.
    Returns the detected version based on schema inspection.
    """
    # Check if users table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    )
    if not cursor.fetchone():
        return 0  # No users table means version 0

    # Check for columns added in version 1
    columns = get_table_columns(cursor, "users")
    if "full_name" in columns and "anthropic_api_key" in columns:
        return 1  # Has v1 columns

    return 0  # Original schema


def bootstrap_schema_version(cursor: sqlite3.Cursor) -> int:
    """Bootstrap the schema_version table for an existing database.

    Detects the current state and inserts appropriate version records.
    Returns the detected version.
    """
    detected_version = detect_current_state(cursor)

    if detected_version >= 1:
        # Insert version 1 record (bootstrapped)
        cursor.execute(
            """
            INSERT OR IGNORE INTO schema_version
            (version, migrate_script, revert_script, description, applied_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                1,
                "db_migrate_0_to_1.py",
                "db_revert_1_to_0.py",
                "Add full_name and anthropic_api_key to users table (bootstrapped)",
                datetime.now().isoformat(),
            ),
        )

    return detected_version


def load_migration_module(script_name: str) -> Any:
    """Load a migration module by name."""
    module_name = f"scripts.migrations.{script_name.replace('.py', '')}"
    return importlib.import_module(module_name)


def get_available_migrations() -> list[dict[str, Any]]:
    """Get list of available migration scripts.

    Returns a list of dicts with source_version, target_version, script_name, description.
    """
    migrations_dir = Path(__file__).parent
    migrations = []

    for script_file in migrations_dir.glob("db_migrate_*.py"):
        try:
            module = load_migration_module(script_file.name)
            migrations.append({
                "source_version": module.SOURCE_VERSION,
                "target_version": module.TARGET_VERSION,
                "script_name": script_file.name,
                "description": module.DESCRIPTION,
                "type": "migrate",
            })
        except (ImportError, AttributeError) as e:
            print(f"Warning: Could not load migration {script_file.name}: {e}")

    for script_file in migrations_dir.glob("db_revert_*.py"):
        try:
            module = load_migration_module(script_file.name)
            migrations.append({
                "source_version": module.SOURCE_VERSION,
                "target_version": module.TARGET_VERSION,
                "script_name": script_file.name,
                "description": module.DESCRIPTION,
                "type": "revert",
            })
        except (ImportError, AttributeError) as e:
            print(f"Warning: Could not load revert script {script_file.name}: {e}")

    return migrations


def find_migration_path(
    current_version: int,
    target_version: int,
    migrations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find the sequence of migrations to apply.

    Returns list of migration dicts in order of application.
    """
    if current_version == target_version:
        return []

    going_up = target_version > current_version
    migration_type = "migrate" if going_up else "revert"

    # Filter to relevant migrations
    relevant = [m for m in migrations if m["type"] == migration_type]

    path = []
    version = current_version

    while version != target_version:
        # Find migration from current version
        next_migration = None
        for m in relevant:
            if m["source_version"] == version:
                if going_up and m["target_version"] > version:
                    next_migration = m
                    break
                elif not going_up and m["target_version"] < version:
                    next_migration = m
                    break

        if next_migration is None:
            raise ValueError(
                f"No migration found from version {version} "
                f"{'up' if going_up else 'down'} to {target_version}"
            )

        path.append(next_migration)
        version = next_migration["target_version"]

    return path


def get_latest_version(migrations: list[dict[str, Any]]) -> int:
    """Get the latest available version from migrations."""
    versions = set()
    for m in migrations:
        versions.add(m["source_version"])
        versions.add(m["target_version"])
    return max(versions) if versions else 0


def apply_migration(
    cursor: sqlite3.Cursor,
    migration: dict[str, Any],
    dry_run: bool = False,
) -> bool:
    """Apply a single migration.

    Returns True if successful, False otherwise.
    """
    script_name = migration["script_name"]
    is_revert = migration["type"] == "revert"

    print(f"Applying {script_name}...")
    print(f"  {migration['description']}")

    if dry_run:
        print("  [DRY RUN] Would apply migration")
        return True

    try:
        module = load_migration_module(script_name)
        module.migrate(cursor)

        # Validate the migration
        if hasattr(module, "validate"):
            if not module.validate(cursor):
                raise RuntimeError(f"Migration validation failed for {script_name}")

        # Update schema_version table
        if is_revert:
            # Remove the version record we're reverting from
            cursor.execute(
                "DELETE FROM schema_version WHERE version = ?",
                (migration["source_version"],),
            )
        else:
            # Get revert script name
            revert_script = f"db_revert_{migration['target_version']}_to_{migration['source_version']}.py"
            cursor.execute(
                """
                INSERT INTO schema_version
                (version, migrate_script, revert_script, description, applied_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    migration["target_version"],
                    script_name,
                    revert_script,
                    migration["description"],
                    datetime.now().isoformat(),
                ),
            )

        print("  Done.")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def cmd_status(args: argparse.Namespace) -> int:
    """Show current database status."""
    db_path = get_db_path(args.database)

    if not Path(db_path).exists():
        print(f"Database not found at: {db_path}")
        print("Current version: 0 (database will be created when app starts)")
        return 0

    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        ensure_schema_version_table(cursor)
        current_version = get_current_version(cursor)

        # If version is 0, check if we need to bootstrap
        if current_version == 0:
            detected = detect_current_state(cursor)
            if detected > 0:
                print(f"Database at: {db_path}")
                print(f"Detected version: {detected} (schema_version table not initialized)")
                print()
                print("Run 'up' to initialize schema_version table and bring to latest version.")
                conn.close()
                return 0

        migrations = get_available_migrations()
        latest_version = get_latest_version(migrations)

        print(f"Database at: {db_path}")
        print(f"Current version: {current_version}")
        print(f"Latest version: {latest_version}")

        if current_version < latest_version:
            print()
            print("Available migrations:")
            path = find_migration_path(current_version, latest_version, migrations)
            for m in path:
                print(f"  {m['script_name']}: {m['description']}")
        elif current_version == latest_version:
            print()
            print("Database is up to date.")

        conn.close()
        return 0

    except Exception as e:
        print(f"Error: {e}")
        conn.close()
        return 1


def cmd_up(args: argparse.Namespace) -> int:
    """Migrate up to target version."""
    db_path = get_db_path(args.database)

    if not Path(db_path).exists():
        print(f"Database not found at: {db_path}")
        print("The database will be created when the app starts.")
        print("Run the app first, then run migrations if needed.")
        return 1

    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        ensure_schema_version_table(cursor)
        conn.commit()

        current_version = get_current_version(cursor)

        # Bootstrap if needed
        if current_version == 0:
            detected = detect_current_state(cursor)
            if detected > 0:
                print(f"Bootstrapping schema_version table at version {detected}...")
                bootstrap_schema_version(cursor)
                conn.commit()
                current_version = detected

        migrations = get_available_migrations()
        latest_version = get_latest_version(migrations)
        target_version = args.to if args.to is not None else latest_version

        if target_version < current_version:
            print(f"Target version {target_version} is less than current version {current_version}.")
            print("Use 'down' command to revert.")
            conn.close()
            return 1

        if current_version == target_version:
            print(f"Already at version {current_version}. Nothing to do.")
            conn.close()
            return 0

        print(f"Migrating from version {current_version} to {target_version}...")
        print()

        path = find_migration_path(current_version, target_version, migrations)

        for migration in path:
            if not apply_migration(cursor, migration, args.dry_run):
                print()
                print("Migration failed. Rolling back...")
                conn.rollback()
                conn.close()
                return 1

            if not args.dry_run:
                conn.commit()

        print()
        print(f"Successfully migrated to version {target_version}.")
        conn.close()
        return 0

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        conn.close()
        return 1


def cmd_down(args: argparse.Namespace) -> int:
    """Revert down to target version."""
    db_path = get_db_path(args.database)

    if not Path(db_path).exists():
        print(f"Database not found at: {db_path}")
        return 1

    if args.to is None:
        print("Error: --to VERSION is required for down command")
        return 1

    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        ensure_schema_version_table(cursor)
        current_version = get_current_version(cursor)

        # Bootstrap if needed
        if current_version == 0:
            detected = detect_current_state(cursor)
            if detected > 0:
                print(f"Bootstrapping schema_version table at version {detected}...")
                bootstrap_schema_version(cursor)
                conn.commit()
                current_version = detected

        target_version = args.to

        if target_version > current_version:
            print(f"Target version {target_version} is greater than current version {current_version}.")
            print("Use 'up' command to migrate forward.")
            conn.close()
            return 1

        if target_version < 0:
            print("Target version cannot be negative.")
            conn.close()
            return 1

        if current_version == target_version:
            print(f"Already at version {current_version}. Nothing to do.")
            conn.close()
            return 0

        print(f"Reverting from version {current_version} to {target_version}...")
        print("WARNING: This may result in data loss!")
        print()

        migrations = get_available_migrations()
        path = find_migration_path(current_version, target_version, migrations)

        for migration in path:
            if not apply_migration(cursor, migration, args.dry_run):
                print()
                print("Revert failed. Rolling back...")
                conn.rollback()
                conn.close()
                return 1

            if not args.dry_run:
                conn.commit()

        print()
        print(f"Successfully reverted to version {target_version}.")
        conn.close()
        return 0

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        conn.close()
        return 1


def cmd_history(args: argparse.Namespace) -> int:
    """Show migration history."""
    db_path = get_db_path(args.database)

    if not Path(db_path).exists():
        print(f"Database not found at: {db_path}")
        return 1

    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        # Check if schema_version table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if not cursor.fetchone():
            print("No migration history (schema_version table does not exist).")
            conn.close()
            return 0

        cursor.execute(
            """
            SELECT version, migrate_script, description, applied_at
            FROM schema_version
            ORDER BY version
            """
        )
        rows = cursor.fetchall()

        if not rows:
            print("No migrations have been applied.")
        else:
            print("Migration history:")
            print()
            print(f"{'Version':<10} {'Applied At':<25} {'Description'}")
            print("-" * 80)
            for row in rows:
                version, script, description, applied_at = row
                print(f"{version:<10} {applied_at:<25} {description}")

        conn.close()
        return 0

    except Exception as e:
        print(f"Error: {e}")
        conn.close()
        return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Database migration runner for WineBox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s status                    Show current version and available migrations
  %(prog)s up                        Migrate to latest version
  %(prog)s up --to 2                 Migrate to specific version
  %(prog)s down --to 0               Revert to specific version
  %(prog)s history                   Show migration history
        """,
    )

    parser.add_argument(
        "-d", "--database",
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # status command
    status_parser = subparsers.add_parser("status", help="Show current database status")
    status_parser.set_defaults(func=cmd_status)

    # up command
    up_parser = subparsers.add_parser("up", help="Migrate up to target version")
    up_parser.add_argument(
        "--to",
        type=int,
        help="Target version (default: latest)",
    )
    up_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without applying changes",
    )
    up_parser.set_defaults(func=cmd_up)

    # down command
    down_parser = subparsers.add_parser("down", help="Revert down to target version")
    down_parser.add_argument(
        "--to",
        type=int,
        required=True,
        help="Target version to revert to",
    )
    down_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without applying changes",
    )
    down_parser.set_defaults(func=cmd_down)

    # history command
    history_parser = subparsers.add_parser("history", help="Show migration history")
    history_parser.set_defaults(func=cmd_history)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
