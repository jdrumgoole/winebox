#!/usr/bin/env python3
"""Backup and restore X-Wines collections to/from S3 using mongodump/mongorestore.

Uses native MongoDB tools (mongodump/mongorestore) for fast, reliable
binary backups. Each backup is a gzipped archive of the BSON dump,
uploaded to S3 with a manifest.

Credentials are read from environment variables or .env file:
  - WINEBOX_MONGODB_URL: MongoDB connection string
  - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY: AWS credentials
  - WINEBOX_S3_BUCKET: S3 bucket name (required)
  - WINEBOX_S3_PREFIX: Key prefix (default: "backups/xwines")
  - AWS_REGION: AWS region (default: "eu-west-1")

Usage:
    # Backup
    uv run python scripts/backup_xwines_to_s3.py backup
    uv run python scripts/backup_xwines_to_s3.py backup --collections xwines_prices
    uv run python scripts/backup_xwines_to_s3.py backup --database winebox-oat --retain 5

    # Restore
    uv run python scripts/backup_xwines_to_s3.py restore --timestamp 2026-03-21_014500
    uv run python scripts/backup_xwines_to_s3.py restore --latest
    uv run python scripts/backup_xwines_to_s3.py restore --latest --database winebox-oat-staging

    # List existing backups
    uv run python scripts/backup_xwines_to_s3.py list

    # Dry run
    uv run python scripts/backup_xwines_to_s3.py backup --dry-run
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

XWINES_COLLECTIONS = ["xwines_wines", "xwines_prices", "xwines_metadata"]


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


def check_tool(name: str) -> str:
    """Check that a command-line tool is available and return its path."""
    path = shutil.which(name)
    if not path:
        print(f"Error: '{name}' not found. Install MongoDB Database Tools:", file=sys.stderr)
        print("  brew install mongodb-database-tools", file=sys.stderr)
        sys.exit(1)
    return path


def run_mongodump(
    mongodb_url: str,
    database: str,
    collections: list[str],
    output_dir: Path,
) -> None:
    """Run mongodump for the specified collections.

    Args:
        mongodb_url: MongoDB connection string.
        database: Database name.
        collections: List of collection names to dump.
        output_dir: Directory to write dump files to.
    """
    mongodump = check_tool("mongodump")

    for col_name in collections:
        logger.info("Dumping %s.%s ...", database, col_name)
        cmd = [
            mongodump,
            f"--uri={mongodb_url}",
            f"--db={database}",
            f"--collection={col_name}",
            f"--out={output_dir}",
            "--gzip",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"mongodump failed for {col_name}:\n{result.stderr}"
            )
        # Count documents from dump metadata
        bson_file = output_dir / database / f"{col_name}.bson.gz"
        if bson_file.exists():
            size_mb = bson_file.stat().st_size / (1024 * 1024)
            print(f"  {col_name}: dumped ({size_mb:.1f} MB)")
        else:
            print(f"  {col_name}: dumped")


def run_mongorestore(
    mongodb_url: str,
    database: str,
    dump_dir: Path,
    drop: bool = True,
) -> None:
    """Run mongorestore from a dump directory.

    Args:
        mongodb_url: MongoDB connection string.
        database: Target database name.
        dump_dir: Directory containing the dump files (parent of db-named dir).
        drop: If True, drop existing collections before restoring.
    """
    mongorestore = check_tool("mongorestore")

    cmd = [
        mongorestore,
        f"--uri={mongodb_url}",
        f"--db={database}",
        "--gzip",
        "--nsInclude=*",
    ]
    if drop:
        cmd.append("--drop")

    # Find the database directory inside the dump
    # mongodump creates: dump_dir/<original_db_name>/<collection>.bson.gz
    db_dirs = [d for d in dump_dir.iterdir() if d.is_dir()]
    if not db_dirs:
        raise RuntimeError(f"No database directory found in dump at {dump_dir}")

    source_db_dir = db_dirs[0]
    # mongorestore needs the path to the db directory
    cmd.append(str(source_db_dir))

    logger.info("Restoring to %s from %s ...", database, source_db_dir.name)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"mongorestore failed:\n{result.stderr}")

    # List restored collections
    for f in sorted(source_db_dir.iterdir()):
        if f.suffix == ".gz" and f.stem.endswith(".bson"):
            col_name = f.stem.replace(".bson", "")
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  Restored {col_name} ({size_mb:.1f} MB)")


def create_archive(dump_dir: Path, archive_path: Path) -> None:
    """Create a tar.gz archive from the dump directory.

    Args:
        dump_dir: Directory containing mongodump output.
        archive_path: Path for the output .tar.gz file.
    """
    with tarfile.open(archive_path, "w:gz") as tar:
        for item in dump_dir.iterdir():
            tar.add(item, arcname=item.name)


def extract_archive(archive_path: Path, output_dir: Path) -> None:
    """Extract a tar.gz archive.

    Args:
        archive_path: Path to the .tar.gz file.
        output_dir: Directory to extract to.
    """
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=output_dir)


def get_collection_counts(mongodb_url: str, database: str, collections: list[str]) -> dict[str, int]:
    """Get document counts for collections."""
    from pymongo import MongoClient

    client = MongoClient(mongodb_url)
    db = client[database]
    counts = {}
    for col_name in collections:
        counts[col_name] = db[col_name].count_documents({})
    client.close()
    return counts


# --- Backup ---

def cmd_backup(args: argparse.Namespace) -> int:
    """Run the backup command."""
    mongodb_url = get_mongodb_url()
    bucket = get_s3_bucket()
    prefix = get_s3_prefix()
    database = args.database
    collections = args.collections
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")

    counts = get_collection_counts(mongodb_url, database, collections)

    print(f"\nX-Wines S3 Backup (mongodump)")
    print("=" * 50)
    print(f"Database:    {database}")
    print(f"Collections: {', '.join(collections)}")
    print(f"S3 target:   s3://{bucket}/{prefix}/{timestamp}/")
    print()
    for col_name in collections:
        print(f"  {col_name}: {counts.get(col_name, 0):,} documents")

    if args.dry_run:
        print("\n[DRY RUN] Would dump and upload the above. No changes made.")
        return 0

    print()

    s3_client = get_s3_client()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        dump_dir = tmpdir_path / "dump"
        dump_dir.mkdir()

        # Run mongodump
        run_mongodump(mongodb_url, database, collections, dump_dir)

        # Create archive
        archive_name = f"{database}_xwines_{timestamp}.tar.gz"
        archive_path = tmpdir_path / archive_name
        print(f"\n  Creating archive: {archive_name}")
        create_archive(dump_dir, archive_path)
        archive_size_mb = archive_path.stat().st_size / (1024 * 1024)
        print(f"  Archive size: {archive_size_mb:.1f} MB")

        # Upload archive
        s3_key = f"{prefix}/{timestamp}/{archive_name}"
        print(f"  Uploading to s3://{bucket}/{s3_key}")
        s3_client.upload_file(
            str(archive_path),
            bucket,
            s3_key,
            ExtraArgs={"ContentType": "application/gzip"},
        )

    # Write manifest
    manifest = {
        "timestamp": timestamp,
        "database": database,
        "collections": {col: {"document_count": counts.get(col, 0)} for col in collections},
        "archive": archive_name,
        "tool": "mongodump",
    }
    manifest_key = f"{prefix}/{timestamp}/manifest.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )
    print(f"  Wrote manifest to s3://{bucket}/{manifest_key}")

    # Cleanup old backups
    if args.retain is not None:
        print(f"\nCleaning up old backups (keeping {args.retain} most recent)...")
        deleted = cleanup_old_backups(s3_client, bucket, prefix, args.retain)
        if deleted:
            print(f"  Deleted {deleted} old backup files")
        else:
            print("  No old backups to delete")

    print(f"\nBackup complete!")
    return 0


# --- Restore ---

def cmd_restore(args: argparse.Namespace) -> int:
    """Run the restore command."""
    mongodb_url = get_mongodb_url()
    bucket = get_s3_bucket()
    prefix = get_s3_prefix()
    database = args.database

    s3_client = get_s3_client()

    # Determine which backup to restore
    if args.latest:
        timestamps = get_backup_timestamps(s3_client, bucket, prefix)
        if not timestamps:
            print("No backups found.", file=sys.stderr)
            return 1
        timestamp = timestamps[0]
        print(f"Using latest backup: {timestamp}")
    elif args.timestamp:
        timestamp = args.timestamp
    else:
        print("Error: specify --latest or --timestamp TIMESTAMP", file=sys.stderr)
        return 1

    # Download manifest
    manifest_key = f"{prefix}/{timestamp}/manifest.json"
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=manifest_key)
        manifest = json.loads(resp["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        print(f"No manifest found for timestamp {timestamp}", file=sys.stderr)
        return 1

    archive_name = manifest.get("archive")
    source_db = manifest.get("database", "unknown")
    collections = manifest.get("collections", {})

    print(f"\nX-Wines S3 Restore (mongorestore)")
    print("=" * 50)
    print(f"Backup:      {timestamp}")
    print(f"Source DB:   {source_db}")
    print(f"Target DB:   {database}")
    print(f"Archive:     {archive_name}")
    print(f"Collections:")
    for col_name, info in collections.items():
        print(f"  {col_name}: {info.get('document_count', '?'):,} documents")

    if args.dry_run:
        print("\n[DRY RUN] Would download and restore the above. No changes made.")
        return 0

    if not args.force:
        confirm = input(f"\nThis will DROP and replace collections in '{database}'. Continue? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            return 0

    print()

    s3_key = f"{prefix}/{timestamp}/{archive_name}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Download archive
        archive_path = tmpdir_path / archive_name
        print(f"  Downloading s3://{bucket}/{s3_key} ...")
        s3_client.download_file(bucket, s3_key, str(archive_path))
        archive_size_mb = archive_path.stat().st_size / (1024 * 1024)
        print(f"  Downloaded: {archive_size_mb:.1f} MB")

        # Extract
        dump_dir = tmpdir_path / "dump"
        dump_dir.mkdir()
        print(f"  Extracting archive...")
        extract_archive(archive_path, dump_dir)

        # Restore
        run_mongorestore(mongodb_url, database, dump_dir, drop=True)

    # Verify counts
    print(f"\nVerifying restore...")
    actual_counts = get_collection_counts(mongodb_url, database, list(collections.keys()))
    all_ok = True
    for col_name, info in collections.items():
        expected = info.get("document_count", 0)
        actual = actual_counts.get(col_name, 0)
        status = "OK" if actual == expected else "MISMATCH"
        if status == "MISMATCH":
            all_ok = False
        print(f"  {col_name}: {actual:,} documents (expected {expected:,}) [{status}]")

    if all_ok:
        print(f"\nRestore complete! All document counts match.")
    else:
        print(f"\nRestore completed with count mismatches — verify data manually.")

    return 0


# --- List ---

def get_backup_timestamps(s3_client: Any, bucket: str, prefix: str) -> list[str]:
    """Get sorted list of backup timestamps (newest first)."""
    timestamps = set()
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            parts = obj["Key"].split("/")
            for part in parts:
                if len(part) >= 15 and part[4:5] == "-" and part[7:8] == "-" and part[10:11] == "_":
                    timestamps.add(part)
                    break

    return sorted(timestamps, reverse=True)


def cmd_list(args: argparse.Namespace) -> int:
    """List existing backups."""
    bucket = get_s3_bucket()
    prefix = get_s3_prefix()
    s3_client = get_s3_client()

    timestamps = get_backup_timestamps(s3_client, bucket, prefix)

    if not timestamps:
        print(f"No backups found in s3://{bucket}/{prefix}/")
        return 0

    print(f"\nBackups in s3://{bucket}/{prefix}/")
    print("=" * 60)

    for ts in timestamps:
        # Try to read manifest
        manifest_key = f"{prefix}/{ts}/manifest.json"
        try:
            resp = s3_client.get_object(Bucket=bucket, Key=manifest_key)
            manifest = json.loads(resp["Body"].read())
            db_name = manifest.get("database", "?")
            collections = manifest.get("collections", {})
            total_docs = sum(c.get("document_count", 0) for c in collections.values())
            cols = ", ".join(collections.keys())
            print(f"\n  {ts}  [{db_name}]")
            print(f"    {total_docs:,} documents across {len(collections)} collections ({cols})")
        except Exception:
            print(f"\n  {ts}  (no manifest)")

    return 0


# --- Cleanup ---

def cleanup_old_backups(
    s3_client: Any, bucket: str, prefix: str, retain: int
) -> int:
    """Delete old backup sets, keeping the most recent N."""
    timestamps = get_backup_timestamps(s3_client, bucket, prefix)

    if len(timestamps) <= retain:
        return 0

    to_delete = timestamps[retain:]
    deleted = 0

    for ts in to_delete:
        # List all objects under this timestamp
        ts_prefix = f"{prefix}/{ts}/"
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=ts_prefix):
            for obj in page.get("Contents", []):
                logger.info("  Deleting s3://%s/%s", bucket, obj["Key"])
                s3_client.delete_object(Bucket=bucket, Key=obj["Key"])
                deleted += 1

    return deleted


# --- CLI ---

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Backup and restore X-Wines collections to/from S3 using mongodump",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Backup collections to S3")
    backup_parser.add_argument(
        "--database",
        default=os.environ.get("WINEBOX_DATABASE", "winebox-oat"),
        help="MongoDB database name (default: winebox-oat)",
    )
    backup_parser.add_argument(
        "--collections",
        nargs="+",
        default=XWINES_COLLECTIONS,
        choices=XWINES_COLLECTIONS,
        help=f"Collections to backup (default: all)",
    )
    backup_parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    backup_parser.add_argument(
        "--retain", type=int, default=None,
        help="Keep only N most recent backup sets",
    )

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore collections from S3")
    restore_parser.add_argument(
        "--database",
        default=os.environ.get("WINEBOX_DATABASE", "winebox-oat"),
        help="Target MongoDB database name (default: winebox-oat)",
    )
    restore_group = restore_parser.add_mutually_exclusive_group(required=True)
    restore_group.add_argument("--latest", action="store_true", help="Restore the most recent backup")
    restore_group.add_argument("--timestamp", help="Restore a specific backup (e.g. 2026-03-21_014500)")
    restore_parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    restore_parser.add_argument(
        "--force", action="store_true",
        help="Skip confirmation prompt",
    )

    # List command
    subparsers.add_parser("list", help="List existing backups")

    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

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
        if args.command == "backup":
            return cmd_backup(args)
        elif args.command == "restore":
            return cmd_restore(args)
        elif args.command == "list":
            return cmd_list(args)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            return 1

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
