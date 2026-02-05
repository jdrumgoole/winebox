"""Database migration system for WineBox.

This package provides versioned database migrations with forward and reverse support.

Usage:
    # Show current version and available migrations
    uv run python -m scripts.migrations.runner status

    # Migrate to latest version
    uv run python -m scripts.migrations.runner up

    # Migrate to specific version
    uv run python -m scripts.migrations.runner up --to 2

    # Revert to specific version
    uv run python -m scripts.migrations.runner down --to 0

    # Show migration history
    uv run python -m scripts.migrations.runner history
"""
