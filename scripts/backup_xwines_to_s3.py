#!/usr/bin/env python3
"""Backup X-Wines collections (xwines_wines, xwines_prices, xwines_metadata) to S3.

Exports each collection as gzipped JSON Lines (.jsonl.gz) and uploads to S3.
Supports full and incremental backups, with automatic cleanup of old backups.

Credentials are read from environment variables or .env file:
  - WINEBOX_MONGODB_URL: MongoDB connection string
  - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY: AWS credentials
  - WINEBOX_S3_BUCKET: S3 bucket name (required)
  - WINEBOX_S3_PREFIX: Key prefix (default: "backups/xwines")
  - AWS_REGION: AWS region (default: "eu-west-1")

Usage:
    uv run python scripts/backup_xwines_to_s3.py
    uv run python scripts/backup_xwines_to_s3.py --collections xwines_prices
    uv run python scripts/backup_xwines_to_s3.py --database winebox-oat
    uv run python scripts/backup_xwines_to_s3.py --list
    uv run python scripts/backup_xwines_to_s3.py --retain 5
    uv run python scripts/backup_xwines_to_s3.py --dry-run
"""

import argparse
import gzip
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo import MongoClient

logger = logging.getLogger(__name__)

XWINES_COLLECTIONS = ["xwines_wines", "xwines_prices", "xwines_metadata"]


class BSONEncoder(json.JSONEncoder):
    """JSON encoder that handles BSON types (ObjectId, datetime)."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def load_env() -> None:
    """Load environment variables from .env file if present."""
    for env_path in [Path.cwd() / ".env", Path.cwd() / "secrets.env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    value = value.strip()
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    if key not in os.environ:
                        os.environ[key] = value


def get_mongodb_url() -> str:
    """Get MongoDB connection URL from environment."""
    url = os.environ.get("WINEBOX_MONGODB_URL")
    if not url:
        raise ValueError(
            "WINEBOX_MONGODB_URL not set. Add it to .env or set as environment variable."
        )
    return url


def get_s3_client() -> Any:
    """Create a boto3 S3 client."""
    import boto3

    region = os.environ.get("AWS_REGION", "eu-west-1")
    return boto3.client("s3", region_name=region)


def get_s3_bucket() -> str:
    """Get the S3 bucket name from environment."""
    bucket = os.environ.get("WINEBOX_S3_BUCKET")
    if not bucket:
        raise ValueError(
            "WINEBOX_S3_BUCKET not set. Add it to .env or set as environment variable."
        )
    return bucket


def get_s3_prefix() -> str:
    """Get the S3 key prefix from environment."""
    return os.environ.get("WINEBOX_S3_PREFIX", "backups/xwines")


def export_collection_to_file(
    db: Any, collection_name: str, output_path: Path
) -> int:
    """Export a MongoDB collection to a gzipped JSONL file.

    Args:
        db: pymongo Database instance.
        collection_name: Name of the collection to export.
        output_path: Path to write the .jsonl.gz file.

    Returns:
        Number of documents exported.
    """
    collection = db[collection_name]
    count = 0

    with gzip.open(output_path, "wt", encoding="utf-8") as f:
        for doc in collection.find():
            line = json.dumps(doc, cls=BSONEncoder)
            f.write(line + "\n")
            count += 1
            if count % 10000 == 0:
                logger.info("  %s: %d documents exported...", collection_name, count)

    return count


def upload_to_s3(
    s3_client: Any, bucket: str, key: str, file_path: Path
) -> None:
    """Upload a file to S3.

    Args:
        s3_client: boto3 S3 client.
        bucket: S3 bucket name.
        key: S3 object key.
        file_path: Local file path to upload.
    """
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    logger.info("  Uploading %s (%.1f MB) to s3://%s/%s", file_path.name, file_size_mb, bucket, key)

    s3_client.upload_file(
        str(file_path),
        bucket,
        key,
        ExtraArgs={"ContentType": "application/gzip"},
    )


def list_backups(s3_client: Any, bucket: str, prefix: str) -> list[dict]:
    """List existing backups in S3.

    Returns:
        List of dicts with key, size, last_modified for each backup file.
    """
    backups = []
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            backups.append(
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                }
            )

    return sorted(backups, key=lambda b: b["last_modified"], reverse=True)


def cleanup_old_backups(
    s3_client: Any, bucket: str, prefix: str, retain: int
) -> int:
    """Delete old backup sets, keeping the most recent N.

    A backup set is identified by its timestamp directory.

    Args:
        s3_client: boto3 S3 client.
        bucket: S3 bucket name.
        prefix: S3 key prefix.
        retain: Number of backup sets to keep.

    Returns:
        Number of files deleted.
    """
    backups = list_backups(s3_client, bucket, prefix)
    if not backups:
        return 0

    # Group by timestamp directory (prefix/YYYY-MM-DD_HHMMSS/)
    timestamps: dict[str, list[str]] = {}
    for b in backups:
        parts = b["key"].split("/")
        # Find the timestamp part (e.g., "2026-03-21_014500")
        ts_part = None
        for part in parts:
            if len(part) >= 15 and part[4] == "-" and part[7] == "-" and part[10] == "_":
                ts_part = part
                break
        if ts_part:
            timestamps.setdefault(ts_part, []).append(b["key"])

    sorted_timestamps = sorted(timestamps.keys(), reverse=True)

    if len(sorted_timestamps) <= retain:
        return 0

    # Delete oldest backup sets
    to_delete = sorted_timestamps[retain:]
    deleted = 0
    for ts in to_delete:
        for key in timestamps[ts]:
            logger.info("  Deleting old backup: s3://%s/%s", bucket, key)
            s3_client.delete_object(Bucket=bucket, Key=key)
            deleted += 1

    return deleted


def run_backup(
    database: str,
    collections: list[str],
    dry_run: bool = False,
    retain: int | None = None,
) -> None:
    """Run the backup process.

    Args:
        database: MongoDB database name.
        collections: List of collection names to backup.
        dry_run: If True, show plan without uploading.
        retain: If set, delete old backups keeping this many sets.
    """
    mongodb_url = get_mongodb_url()
    bucket = get_s3_bucket()
    prefix = get_s3_prefix()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")

    client = MongoClient(mongodb_url)
    db = client[database]

    print(f"\nX-Wines S3 Backup")
    print("=" * 50)
    print(f"Database: {database}")
    print(f"Collections: {', '.join(collections)}")
    print(f"S3 bucket: {bucket}")
    print(f"S3 prefix: {prefix}/{timestamp}/")
    print()

    # Show collection sizes
    for col_name in collections:
        count = db[col_name].count_documents({})
        print(f"  {col_name}: {count:,} documents")

    if dry_run:
        print("\n[DRY RUN] Would export and upload the above. No changes made.")
        client.close()
        return

    print()

    s3_client = get_s3_client()

    with tempfile.TemporaryDirectory() as tmpdir:
        for col_name in collections:
            filename = f"{col_name}.jsonl.gz"
            local_path = Path(tmpdir) / filename
            s3_key = f"{prefix}/{timestamp}/{database}_{filename}"

            # Export
            logger.info("Exporting %s...", col_name)
            count = export_collection_to_file(db, col_name, local_path)
            file_size_mb = local_path.stat().st_size / (1024 * 1024)
            print(f"  Exported {col_name}: {count:,} documents ({file_size_mb:.1f} MB)")

            # Upload
            upload_to_s3(s3_client, bucket, s3_key, local_path)
            print(f"  Uploaded to s3://{bucket}/{s3_key}")

    # Write a manifest file
    manifest = {
        "timestamp": timestamp,
        "database": database,
        "collections": {},
    }
    for col_name in collections:
        count = db[col_name].count_documents({})
        manifest["collections"][col_name] = {"document_count": count}

    manifest_key = f"{prefix}/{timestamp}/manifest.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )
    print(f"  Wrote manifest to s3://{bucket}/{manifest_key}")

    # Cleanup old backups if requested
    if retain is not None:
        print(f"\nCleaning up old backups (keeping {retain} most recent)...")
        deleted = cleanup_old_backups(s3_client, bucket, prefix, retain)
        if deleted:
            print(f"  Deleted {deleted} old backup files")
        else:
            print("  No old backups to delete")

    client.close()
    print(f"\nBackup complete!")


def show_backups() -> None:
    """List existing backups in S3."""
    bucket = get_s3_bucket()
    prefix = get_s3_prefix()
    s3_client = get_s3_client()

    backups = list_backups(s3_client, bucket, prefix)

    if not backups:
        print(f"No backups found in s3://{bucket}/{prefix}/")
        return

    print(f"\nExisting backups in s3://{bucket}/{prefix}/")
    print("=" * 70)

    current_ts = None
    for b in backups:
        # Extract timestamp from key
        parts = b["key"].split("/")
        ts_part = None
        for part in parts:
            if len(part) >= 15 and part[4] == "-" and part[7] == "-" and part[10] == "_":
                ts_part = part
                break

        if ts_part and ts_part != current_ts:
            current_ts = ts_part
            print(f"\n  {ts_part}:")

        filename = b["key"].split("/")[-1]
        size_mb = b["size"] / (1024 * 1024)
        modified = b["last_modified"].strftime("%Y-%m-%d %H:%M UTC")
        print(f"    {filename:40s} {size_mb:8.1f} MB  {modified}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Backup X-Wines collections to S3",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("WINEBOX_DATABASE", "winebox-oat"),
        help="MongoDB database name (default: winebox-oat)",
    )
    parser.add_argument(
        "--collections",
        nargs="+",
        default=XWINES_COLLECTIONS,
        choices=XWINES_COLLECTIONS,
        help=f"Collections to backup (default: all — {', '.join(XWINES_COLLECTIONS)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without uploading",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_backups",
        help="List existing backups and exit",
    )
    parser.add_argument(
        "--retain",
        type=int,
        default=None,
        help="Keep only the N most recent backup sets (delete older ones)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Debug logging",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    load_env()

    try:
        if args.list_backups:
            show_backups()
            return 0

        run_backup(
            database=args.database,
            collections=args.collections,
            dry_run=args.dry_run,
            retain=args.retain,
        )
        return 0

    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        return 130
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
