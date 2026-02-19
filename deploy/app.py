#!/usr/bin/env python3
"""Deploy WineBox application to production server.

This script handles deployment of the WineBox application:
1. Installs/upgrades winebox from PyPI
2. Syncs secrets from local .env to production
3. Restarts the service

Usage:
    # Deploy latest version
    python -m deploy.app

    # Deploy specific version
    python -m deploy.app --version 0.4.0

    # Preview changes
    python -m deploy.app --dry-run

Environment variables (in .env):
    WINEBOX_DO_TOKEN - Digital Ocean API token (required for IP lookup)
    WINEBOX_DROPLET_NAME - Droplet name (default: winebox-droplet)
    WINEBOX_DROPLET_IP - Override IP (optional)
"""

import argparse

from deploy.common import (
    DigitalOceanAPI,
    get_env_config,
    resolve_host,
    run_ssh,
    sync_secrets,
)


# =============================================================================
# DNS Setup
# =============================================================================

def setup_dns(
    token: str,
    domain: str,
    droplet_ip: str,
    dry_run: bool = False,
) -> None:
    """Set up A records for the domain.

    Args:
        token: Digital Ocean API token
        domain: Domain name
        droplet_ip: IP address to point to
        dry_run: If True, preview without applying
    """
    client = DigitalOceanAPI(token)

    print(f"Configuring DNS for {domain} -> {droplet_ip}")

    # Get existing records
    existing_records = client.list_dns_records(domain)

    # Records to create/update
    a_records = [
        {"name": "@", "description": "Root domain"},
        {"name": "www", "description": "WWW subdomain"},
    ]

    for record_info in a_records:
        name = record_info["name"]

        # Check if record exists
        existing = next(
            (r for r in existing_records if r["type"] == "A" and r["name"] == name),
            None,
        )

        if existing:
            if existing["data"] == droplet_ip:
                print(f"  A {name} -> {droplet_ip} (already set)")
            else:
                print(f"  A {name} -> {droplet_ip} (updating from {existing['data']})")
                if not dry_run:
                    client.update_dns_record(domain, existing["id"], {
                        "type": "A",
                        "name": name,
                        "data": droplet_ip,
                        "ttl": 300,
                    })
        else:
            print(f"  A {name} -> {droplet_ip} (creating)")
            if not dry_run:
                client.create_dns_record(domain, {
                    "type": "A",
                    "name": name,
                    "data": droplet_ip,
                    "ttl": 300,
                })

    if dry_run:
        print("  DRY RUN - No DNS changes made")
    else:
        print("  DNS records configured!")


# =============================================================================
# Deployment
# =============================================================================

def deploy(
    host: str,
    user: str,
    version: str | None = None,
    env_values: dict[str, str | None] | None = None,
    skip_secrets: bool = False,
    setup_dns_flag: bool = False,
    domain: str = "winebox.app",
    dry_run: bool = False,
) -> None:
    """Deploy WineBox to the production server.

    Args:
        host: Droplet IP address
        user: SSH username
        version: Package version to install (None for latest)
        env_values: Local environment values for secrets sync
        skip_secrets: Skip syncing secrets
        setup_dns_flag: Configure DNS A records
        domain: Domain name
        dry_run: Preview without applying
    """
    print(f"Deploying WineBox to {host}...")
    if version:
        print(f"Version: {version}")
    else:
        print("Version: latest")
    print("=" * 50)

    total_steps = 5 if setup_dns_flag else 4
    step = 0

    # Step: Setup DNS (optional)
    if setup_dns_flag:
        step += 1
        print(f"\n[{step}/{total_steps}] Setting up DNS...")
        token = env_values.get("WINEBOX_DO_TOKEN") if env_values else None
        if token:
            setup_dns(token, domain, host, dry_run)
        else:
            print("  Warning: WINEBOX_DO_TOKEN not found, skipping DNS setup")

    # Step: Install/upgrade from PyPI
    step += 1
    print(f"\n[{step}/{total_steps}] Installing winebox from PyPI...")
    if not dry_run:
        if version:
            pip_spec = f"winebox=={version}"
        else:
            pip_spec = "winebox --upgrade"
        run_ssh(host, user, [
            f"sudo -u winebox /opt/winebox/.venv/bin/pip install {pip_spec}",
        ])

    # Step: Sync secrets
    step += 1
    print(f"\n[{step}/{total_steps}] Syncing secrets...")
    if env_values and not dry_run:
        sync_secrets(host, user, env_values, skip=skip_secrets)
    elif dry_run:
        print("  DRY RUN - Secrets not synced")
    else:
        print("  No local .env loaded, skipping")

    # Step: Restart service
    step += 1
    print(f"\n[{step}/{total_steps}] Restarting service...")
    if not dry_run:
        run_ssh(host, user, ["systemctl restart winebox"])

    # Step: Check status
    step += 1
    print(f"\n[{step}/{total_steps}] Checking service status...")
    if not dry_run:
        run_ssh(host, user, [
            "sleep 2",
            "systemctl is-active winebox",
        ], check=False)

        # Show recent logs
        print("\nRecent logs:")
        run_ssh(host, user, [
            "journalctl -u winebox -n 10 --no-pager",
        ], check=False)

    print("\n" + "=" * 50)
    if dry_run:
        print("DRY RUN complete - no changes made")
    else:
        print("Deployment complete!")
        print(f"Visit https://{domain} to verify")

        if setup_dns_flag:
            print(f"\nDNS was configured. Next steps:")
            print(f"1. Wait 5-10 minutes for DNS propagation")
            print(f"2. Verify: dig {domain} +short")
            print(f"3. Setup SSL: ssh root@{host} 'certbot --nginx -d {domain} -d www.{domain}'")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy WineBox to Digital Ocean droplet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Deploy latest version from PyPI
    python -m deploy.app

    # Deploy specific version
    python -m deploy.app --version 0.4.0

    # First-time setup with DNS
    python -m deploy.app --setup-dns

    # Preview what would happen
    python -m deploy.app --dry-run

    # Deploy without syncing secrets
    python -m deploy.app --no-secrets
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
        "--version",
        help="Package version to install (default: latest)",
    )
    parser.add_argument(
        "--domain",
        default="winebox.app",
        help="Domain name (default: winebox.app)",
    )
    parser.add_argument(
        "--no-secrets",
        action="store_true",
        help="Skip syncing secrets to production",
    )
    parser.add_argument(
        "--setup-dns",
        action="store_true",
        help="Configure DNS A records (first-time setup)",
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
        domain=args.domain,
    )

    # Resolve host
    host = resolve_host(config)

    deploy(
        host=host,
        user=config.user,
        version=args.version,
        env_values=config.env_values,
        skip_secrets=args.no_secrets,
        setup_dns_flag=args.setup_dns,
        domain=config.domain,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
