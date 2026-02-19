#!/usr/bin/env python3
"""Deploy X-Wines dataset to production server.

This script downloads and imports the X-Wines dataset (100K+ wines with
community ratings) to the production MongoDB database.

This is a one-time operation that only needs to be run once after initial
server setup, or when updating to a newer version of the dataset.

Usage:
    # Deploy full dataset (100K+ wines)
    python -m deploy.xwines

    # Deploy test dataset (100 wines, for testing)
    python -m deploy.xwines --test

    # Preview without applying
    python -m deploy.xwines --dry-run

Environment variables (in .env):
    WINEBOX_DO_TOKEN - Digital Ocean API token (for IP lookup)
    WINEBOX_DROPLET_IP - Override droplet IP (optional)
"""

import argparse

from deploy.common import get_env_config, resolve_host, run_ssh


# =============================================================================
# X-Wines Deployment
# =============================================================================

def deploy_xwines(
    host: str,
    user: str,
    version: str = "full",
    dry_run: bool = False,
) -> None:
    """Deploy X-Wines dataset to production server.

    Args:
        host: Droplet IP address
        user: SSH username
        version: Dataset version ("full" or "test")
        dry_run: If True, preview without applying
    """
    print(f"Deploying X-Wines dataset ({version}) to {host}...")
    print("=" * 50)

    if version == "test":
        print("\nUsing test dataset (100 wines)")
        steps = [
            ("Importing test dataset",
             "sudo -u winebox /opt/winebox/.venv/bin/python -m scripts.import_xwines --version test --force"),
        ]
    else:
        print("\nUsing full dataset (100K+ wines)")
        print("This will download ~500MB and may take several minutes.\n")

        steps = [
            # Install gdown for Google Drive downloads
            ("Installing gdown",
             "sudo -u winebox /opt/winebox/.venv/bin/pip install gdown"),

            # Create xwines directory
            ("Creating data directory",
             "sudo -u winebox mkdir -p /opt/winebox/data/xwines"),

            # Download dataset from Google Drive
            ("Downloading X-Wines dataset (this may take a while)",
             'sudo -u winebox bash -c "cd /opt/winebox && '
             '.venv/bin/gdown --folder \\"https://drive.google.com/drive/folders/1LqguJNV-aKh1PuWMVx5ELA61LPfGfuu_?usp=sharing\\" '
             '-O data/xwines/"'),

            # Copy CSV files to expected location
            ("Copying CSV files",
             "sudo -u winebox bash -c 'cp /opt/winebox/data/xwines/X-Wines_Official_Repository/last/XWines_Full_*.csv /opt/winebox/data/xwines/'"),

            # Import into MongoDB
            ("Importing into MongoDB (this may take several minutes)",
             "sudo -u winebox /opt/winebox/.venv/bin/python -m scripts.import_xwines --version full --force"),

            # Clean up downloaded files (keep CSVs)
            ("Cleaning up",
             "sudo -u winebox rm -rf /opt/winebox/data/xwines/X-Wines_Official_Repository"),
        ]

    total_steps = len(steps)
    for i, (description, command) in enumerate(steps, 1):
        print(f"\n[{i}/{total_steps}] {description}...")
        if dry_run:
            print(f"  DRY RUN: {command[:100]}...")
        else:
            run_ssh(host, user, command)

    # Verify import
    print("\n[Verification] Checking X-Wines stats...")
    if not dry_run:
        run_ssh(host, user,
                "curl -s http://localhost:8000/api/xwines/stats | head -c 200",
                check=False)

    print("\n" + "=" * 50)
    if dry_run:
        print("DRY RUN complete - no changes made")
    else:
        print("X-Wines deployment complete!")
        print(f"\nThe wine autocomplete feature is now available with {version} dataset.")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy X-Wines dataset to production server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Deploy full dataset (100K+ wines)
    python -m deploy.xwines

    # Deploy test dataset (100 wines)
    python -m deploy.xwines --test

    # Preview changes
    python -m deploy.xwines --dry-run
""",
    )
    parser.add_argument(
        "--host",
        help="Droplet IP (auto-discovered from API if not set)",
    )
    parser.add_argument(
        "--droplet-name",
        default="winebox-droplet",
        help="Droplet name for IP lookup (default: winebox-droplet)",
    )
    parser.add_argument(
        "--user",
        default="root",
        help="SSH user (default: root)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Use test dataset (100 wines) instead of full dataset",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying",
    )

    args = parser.parse_args()

    # Load configuration
    config = get_env_config(
        host=args.host,
        user=args.user,
        droplet_name=args.droplet_name,
    )

    # Resolve host
    host = resolve_host(config)

    # Determine version
    version = "test" if args.test else "full"

    deploy_xwines(
        host=host,
        user=config.user,
        version=version,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
