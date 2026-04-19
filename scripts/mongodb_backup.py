#!/usr/bin/env python3
"""Backup and restore MongoDB databases to/from S3 using mongodump/mongorestore.

Backs up an entire database as a gzipped mongodump archive. The MongoDB
connection URL specifies both the server and database name.

AWS authentication uses boto3's credential chain — supports:
  - AWS SSO: run `aws sso login --profile winebox_backup` first
  - Named profiles in ~/.aws/credentials (use --profile)
  - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN)
  - IAM instance roles (on EC2/ECS)

Environment variables (.env or shell):
  - WINEBOX_S3_BUCKET: S3 bucket name (required)
  - WINEBOX_S3_PREFIX: Key prefix (default: "backups")
  - AWS_REGION: AWS region (default: "eu-west-1")

Usage:
    # Backup (uses default AWS credentials)
    uv run python scripts/mongodb_backup.py backup "mongodb+srv://user:pass@host/winebox_oat"

    # Backup with a named AWS profile
    uv run python scripts/mongodb_backup.py backup "mongodb+srv://user:pass@host/winebox_oat" --profile winebox_backup

    # Restore latest backup
    uv run python scripts/mongodb_backup.py restore "mongodb+srv://user:pass@host/winebox_oat" --latest

    # Restore to a different database
    uv run python scripts/mongodb_backup.py restore "mongodb+srv://user:pass@host/winebox-staging" --latest

    # List existing backups
    uv run python scripts/mongodb_backup.py list

    # Dry run
    uv run python scripts/mongodb_backup.py backup "mongodb://localhost/mydb" --dry-run
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
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Module-level AWS profile — set from CLI args before any S3 calls
_aws_profile: str | None = None


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


def parse_mongodb_url(url: str) -> tuple[str, str]:
    """Extract the database name and base URL from a MongoDB connection string.

    Args:
        url: Full MongoDB URL like "mongodb+srv://user:pass@host/dbname"

    Returns:
        Tuple of (base_url_without_db, database_name).

    Raises:
        ValueError: If no database name is found in the URL.
    """
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/").split("?")[0]
    if not db_name:
        raise ValueError(
            f"No database name in URL. Use a URL like: mongodb://host:port/DATABASE_NAME"
        )
    return url, db_name


def get_s3_client() -> Any:
    """Create a boto3 S3 client using the credential chain.

    Supports named profiles (--profile), SSO, env vars, and instance roles.
    """
    import boto3

    region = os.environ.get("AWS_REGION", "eu-west-1")
    if _aws_profile:
        session = boto3.Session(profile_name=_aws_profile, region_name=region)
    else:
        session = boto3.Session(region_name=region)
    return session.client("s3")


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
    return os.environ.get("WINEBOX_S3_PREFIX", "backups")


def check_tool(name: str) -> str:
    """Check that a command-line tool is available and return its path."""
    path = shutil.which(name)
    if not path:
        print(f"Error: '{name}' not found. Install MongoDB Database Tools:", file=sys.stderr)
        print("  brew install mongodb-database-tools", file=sys.stderr)
        sys.exit(1)
    return path


def run_mongodump(url: str, database: str, output_dir: Path) -> None:
    """Run mongodump for an entire database."""
    mongodump = check_tool("mongodump")
    cmd = [
        mongodump,
        f"--uri={url}",
        f"--db={database}",
        f"--out={output_dir}",
        "--gzip",
    ]
    print(f"  Running mongodump for '{database}'...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"mongodump failed:\n{result.stderr}")

    # Show what was dumped
    db_dir = output_dir / database
    if db_dir.exists():
        for f in sorted(db_dir.iterdir()):
            if f.name.endswith(".bson.gz"):
                col_name = f.name.replace(".bson.gz", "")
                size_mb = f.stat().st_size / (1024 * 1024)
                print(f"    {col_name}: {size_mb:.1f} MB")


def run_mongorestore(url: str, database: str, dump_dir: Path, drop: bool = True) -> None:
    """Run mongorestore from a dump directory."""
    mongorestore = check_tool("mongorestore")

    # Find the database directory inside the dump
    db_dirs = [d for d in dump_dir.iterdir() if d.is_dir()]
    if not db_dirs:
        raise RuntimeError(f"No database directory found in dump at {dump_dir}")
    source_db_dir = db_dirs[0]

    cmd = [
        mongorestore,
        f"--uri={url}",
        f"--db={database}",
        "--gzip",
        "--nsInclude=*",
    ]
    if drop:
        cmd.append("--drop")
    cmd.append(str(source_db_dir))

    print(f"  Restoring to '{database}' from dump of '{source_db_dir.name}'...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"mongorestore failed:\n{result.stderr}")

    for f in sorted(source_db_dir.iterdir()):
        if f.name.endswith(".bson.gz"):
            col_name = f.name.replace(".bson.gz", "")
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"    {col_name}: {size_mb:.1f} MB")


def get_collection_counts(url: str, database: str) -> dict[str, int]:
    """Get document counts for all collections in a database."""
    from pymongo import MongoClient

    client = MongoClient(url)
    db = client[database]
    counts = {}
    for col_name in db.list_collection_names():
        counts[col_name] = db[col_name].count_documents({})
    client.close()
    return counts


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


def cleanup_old_backups(s3_client: Any, bucket: str, prefix: str, retain: int) -> int:
    """Delete old backup sets, keeping the most recent N."""
    timestamps = get_backup_timestamps(s3_client, bucket, prefix)
    if len(timestamps) <= retain:
        return 0

    deleted = 0
    for ts in timestamps[retain:]:
        ts_prefix = f"{prefix}/{ts}/"
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=ts_prefix):
            for obj in page.get("Contents", []):
                s3_client.delete_object(Bucket=bucket, Key=obj["Key"])
                deleted += 1
    return deleted


# --- Commands ---

def cmd_backup(args: argparse.Namespace) -> int:
    """Backup an entire database to S3."""
    url, database = parse_mongodb_url(args.url)
    bucket = get_s3_bucket()
    prefix = get_s3_prefix()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")

    counts = get_collection_counts(url, database)

    print(f"\nMongoDB S3 Backup")
    print("=" * 50)
    print(f"Database:  {database}")
    print(f"S3 target: s3://{bucket}/{prefix}/{timestamp}/")
    print(f"Collections ({len(counts)}):")
    for col_name in sorted(counts):
        print(f"  {col_name}: {counts[col_name]:,} documents")

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        return 0

    print()
    s3_client = get_s3_client()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        dump_dir = tmpdir_path / "dump"
        dump_dir.mkdir()

        run_mongodump(url, database, dump_dir)

        archive_name = f"{database}_{timestamp}.tar.gz"
        archive_path = tmpdir_path / archive_name
        print(f"\n  Creating archive: {archive_name}")
        with tarfile.open(archive_path, "w:gz") as tar:
            for item in (dump_dir).iterdir():
                tar.add(item, arcname=item.name)
        archive_size_mb = archive_path.stat().st_size / (1024 * 1024)
        print(f"  Archive size: {archive_size_mb:.1f} MB")

        s3_key = f"{prefix}/{timestamp}/{archive_name}"
        print(f"  Uploading to s3://{bucket}/{s3_key}")
        s3_client.upload_file(
            str(archive_path), bucket, s3_key,
            ExtraArgs={"ContentType": "application/gzip"},
        )

    manifest = {
        "timestamp": timestamp,
        "database": database,
        "collections": {col: {"document_count": n} for col, n in counts.items()},
        "archive": archive_name,
    }
    manifest_key = f"{prefix}/{timestamp}/manifest.json"
    s3_client.put_object(
        Bucket=bucket, Key=manifest_key,
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )
    print(f"  Wrote manifest to s3://{bucket}/{manifest_key}")

    if args.retain is not None:
        print(f"\nCleaning up (keeping {args.retain} most recent)...")
        deleted = cleanup_old_backups(s3_client, bucket, prefix, args.retain)
        print(f"  Deleted {deleted} old files" if deleted else "  Nothing to delete")

    print(f"\nBackup complete!")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore a database from S3."""
    url, database = parse_mongodb_url(args.url)
    bucket = get_s3_bucket()
    prefix = get_s3_prefix()
    s3_client = get_s3_client()

    # Determine which backup
    if args.latest:
        timestamps = get_backup_timestamps(s3_client, bucket, prefix)
        if not timestamps:
            print("No backups found.", file=sys.stderr)
            return 1
        timestamp = timestamps[0]
        print(f"Using latest backup: {timestamp}")
    else:
        timestamp = args.timestamp

    # Read manifest
    manifest_key = f"{prefix}/{timestamp}/manifest.json"
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=manifest_key)
        manifest = json.loads(resp["Body"].read())
    except Exception:
        print(f"No manifest found for backup '{timestamp}'", file=sys.stderr)
        return 1

    archive_name = manifest["archive"]
    source_db = manifest.get("database", "?")
    collections = manifest.get("collections", {})

    print(f"\nMongoDB S3 Restore")
    print("=" * 50)
    print(f"Backup:    {timestamp}")
    print(f"Source DB: {source_db}")
    print(f"Target DB: {database}")
    print(f"Collections ({len(collections)}):")
    for col_name, info in sorted(collections.items()):
        print(f"  {col_name}: {info.get('document_count', '?'):,} documents")

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        return 0

    if not args.force:
        confirm = input(f"\nThis will DROP and replace data in '{database}'. Continue? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            return 0

    print()
    s3_key = f"{prefix}/{timestamp}/{archive_name}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        archive_path = tmpdir_path / archive_name

        print(f"  Downloading s3://{bucket}/{s3_key} ...")
        s3_client.download_file(bucket, s3_key, str(archive_path))
        archive_size_mb = archive_path.stat().st_size / (1024 * 1024)
        print(f"  Downloaded: {archive_size_mb:.1f} MB")

        dump_dir = tmpdir_path / "dump"
        dump_dir.mkdir()
        print(f"  Extracting archive...")
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=dump_dir)

        run_mongorestore(url, database, dump_dir, drop=True)

    # Verify
    print(f"\nVerifying...")
    actual = get_collection_counts(url, database)
    all_ok = True
    for col_name, info in sorted(collections.items()):
        expected = info.get("document_count", 0)
        got = actual.get(col_name, 0)
        status = "OK" if got == expected else "MISMATCH"
        if status != "OK":
            all_ok = False
        print(f"  {col_name}: {got:,} (expected {expected:,}) [{status}]")

    print(f"\nRestore {'complete!' if all_ok else 'completed with mismatches.'}")
    return 0


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
        manifest_key = f"{prefix}/{ts}/manifest.json"
        try:
            resp = s3_client.get_object(Bucket=bucket, Key=manifest_key)
            manifest = json.loads(resp["Body"].read())
            db_name = manifest.get("database", "?")
            collections = manifest.get("collections", {})
            total_docs = sum(c.get("document_count", 0) for c in collections.values())
            print(f"\n  {ts}  [{db_name}]  {len(collections)} collections, {total_docs:,} documents")
        except Exception:
            print(f"\n  {ts}  (no manifest)")

    return 0


# --- CLI ---

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Backup and restore MongoDB databases to/from S3",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--profile", default=None,
        help="AWS profile name (e.g. winebox_backup). Uses default credential chain if omitted.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # backup
    bp = subparsers.add_parser("backup", help="Backup a database to S3")
    bp.add_argument("url", help="MongoDB URL including database name (e.g. mongodb://host/dbname)")
    bp.add_argument("--dry-run", action="store_true", help="Show plan only")
    bp.add_argument("--retain", type=int, help="Keep only N most recent backups")

    # restore
    rp = subparsers.add_parser("restore", help="Restore a database from S3")
    rp.add_argument("url", help="MongoDB URL for target database (e.g. mongodb://host/dbname)")
    rg = rp.add_mutually_exclusive_group(required=True)
    rg.add_argument("--latest", action="store_true", help="Restore most recent backup")
    rg.add_argument("--timestamp", help="Restore specific backup (e.g. 2026-03-21_014500)")
    rp.add_argument("--dry-run", action="store_true", help="Show plan only")
    rp.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    # list
    subparsers.add_parser("list", help="List existing backups in S3")

    return parser.parse_args()


def main() -> int:
    global _aws_profile
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_env()
    _aws_profile = args.profile

    try:
        if args.command == "backup":
            return cmd_backup(args)
        elif args.command == "restore":
            return cmd_restore(args)
        elif args.command == "list":
            return cmd_list(args)
    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        return 130
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=args.verbose)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
