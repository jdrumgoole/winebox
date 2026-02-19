#!/usr/bin/env python3
"""Deploy WineBox to Digital Ocean droplet.

This script handles deployment and initial DNS setup:

Deploy (default):
    1. Pulls the latest code from git
    2. Installs/updates dependencies
    3. Syncs secrets from local .env to production
    4. Restarts the service

DNS Setup (--setup-dns):
    Creates A records pointing domain to droplet IP

Usage:
    # Regular deployment (auto-discovers droplet IP)
    python deploy/deploy.py

    # First-time setup with DNS
    python deploy/deploy.py --setup-dns

Environment variables (in .env):
    WINEBOX_DO_TOKEN - Digital Ocean API token (required)
    WINEBOX_DROPLET_NAME - Droplet name (default: winebox-droplet)
    WINEBOX_DROPLET_IP - Override IP (optional, auto-discovered if not set)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values, load_dotenv

# Secrets that should be synced to production
SYNCABLE_SECRETS = [
    "WINEBOX_ANTHROPIC_API_KEY",
    "WINEBOX_SECRET_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
]

# Secrets that should NEVER be synced (production-specific)
NEVER_SYNC = [
    "WINEBOX_MONGODB_URL",
    "WINEBOX_DROPLET_IP",
    "WINEBOX_DO_TOKEN",
]


# =============================================================================
# Digital Ocean API
# =============================================================================

def get_droplet_ip(token: str, droplet_name: str) -> str | None:
    """Get droplet IP address from Digital Ocean API."""
    response = requests.get(
        "https://api.digitalocean.com/v2/droplets",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()

    for droplet in response.json()["droplets"]:
        if droplet["name"] == droplet_name:
            # Get the public IPv4 address
            for network in droplet["networks"]["v4"]:
                if network["type"] == "public":
                    return network["ip_address"]
    return None


# =============================================================================
# SSH Utilities
# =============================================================================

def run_ssh(host: str, user: str, commands: list[str], check: bool = True) -> int:
    """Run commands on remote host via SSH."""
    remote_cmd = " && ".join(commands)

    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        f"{user}@{host}",
        remote_cmd,
    ]

    print(f"Running on {user}@{host}:")
    for cmd in commands:
        print(f"  $ {cmd}")
    print()

    result = subprocess.run(ssh_cmd, check=False)

    if check and result.returncode != 0:
        print(f"Error: Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    return result.returncode


# =============================================================================
# Secrets Sync
# =============================================================================

def sync_secrets(
    host: str,
    user: str,
    local_env: dict[str, str | None],
    skip_secrets: bool = False,
) -> None:
    """Sync secrets from local .env to production."""
    if skip_secrets:
        print("  Skipping secrets sync (--no-secrets)")
        return

    # Build updates dict from syncable secrets
    updates = {}
    for key in SYNCABLE_SECRETS:
        value = local_env.get(key)
        if value:
            updates[key] = value

    if not updates:
        print("  No secrets to sync")
        return

    print(f"  Syncing {len(updates)} secret(s):")
    for key in updates:
        value = updates[key]
        masked = value[:4] + "..." + value[-4:] if len(value) > 12 else "****"
        print(f"    {key}={masked}")

    # Build sed commands to update or append each key
    commands = []
    for key, value in updates.items():
        escaped_value = value.replace("'", "'\\''")
        commands.append(
            f"grep -q '^{key}=' /opt/winebox/.env && "
            f"sed -i 's|^{key}=.*|{key}={escaped_value}|' /opt/winebox/.env || "
            f"echo '{key}={escaped_value}' >> /opt/winebox/.env"
        )

    full_command = " && ".join(commands)
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"{user}@{host}", full_command],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  Warning: Error syncing secrets: {result.stderr}")
    else:
        print("  Secrets synced successfully")


# =============================================================================
# DNS Setup
# =============================================================================

class DigitalOceanDNS:
    """Digital Ocean DNS API client."""

    BASE_URL = "https://api.digitalocean.com/v2"

    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def list_records(self, domain: str) -> list[dict]:
        """List all DNS records for a domain."""
        response = requests.get(
            f"{self.BASE_URL}/domains/{domain}/records",
            headers=self.headers,
            params={"per_page": 100},
        )
        response.raise_for_status()
        return response.json()["domain_records"]

    def create_record(self, domain: str, record: dict) -> dict:
        """Create a DNS record."""
        response = requests.post(
            f"{self.BASE_URL}/domains/{domain}/records",
            headers=self.headers,
            json=record,
        )
        response.raise_for_status()
        return response.json()["domain_record"]

    def update_record(self, domain: str, record_id: int, record: dict) -> dict:
        """Update a DNS record."""
        response = requests.put(
            f"{self.BASE_URL}/domains/{domain}/records/{record_id}",
            headers=self.headers,
            json=record,
        )
        response.raise_for_status()
        return response.json()["domain_record"]


def setup_dns(
    token: str,
    domain: str,
    droplet_ip: str,
    dry_run: bool = False,
) -> None:
    """Set up A records for the domain."""
    client = DigitalOceanDNS(token)

    print(f"Configuring DNS for {domain} -> {droplet_ip}")

    # Get existing records
    existing_records = client.list_records(domain)

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
                    client.update_record(domain, existing["id"], {
                        "type": "A",
                        "name": name,
                        "data": droplet_ip,
                        "ttl": 300,
                    })
        else:
            print(f"  A {name} -> {droplet_ip} (creating)")
            if not dry_run:
                client.create_record(domain, {
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
# Deploy
# =============================================================================

def deploy(
    host: str,
    user: str,
    branch: str = "main",
    local_env: dict[str, str | None] | None = None,
    skip_secrets: bool = False,
    setup_dns_flag: bool = False,
    domain: str = "winebox.app",
    dry_run: bool = False,
) -> None:
    """Deploy WineBox to the droplet."""
    print(f"Deploying WineBox to {host}...")
    print(f"Branch: {branch}")
    print("=" * 50)

    total_steps = 6 if setup_dns_flag else 5
    step = 0

    # Step: Setup DNS (optional)
    if setup_dns_flag:
        step += 1
        print(f"\n[{step}/{total_steps}] Setting up DNS...")
        token = local_env.get("WINEBOX_DO_TOKEN") if local_env else None
        if token:
            setup_dns(token, domain, host, dry_run)
        else:
            print("  Warning: WINEBOX_DO_TOKEN not found, skipping DNS setup")

    # Step: Pull latest code
    step += 1
    print(f"\n[{step}/{total_steps}] Pulling latest code...")
    if not dry_run:
        run_ssh(host, user, [
            "cd /opt/winebox",
            "sudo -u winebox git fetch origin",
            f"sudo -u winebox git checkout {branch}",
            f"sudo -u winebox git pull origin {branch}",
        ])

    # Step: Install dependencies
    step += 1
    print(f"\n[{step}/{total_steps}] Installing dependencies...")
    if not dry_run:
        run_ssh(host, user, [
            "cd /opt/winebox",
            "sudo -u winebox /root/.local/bin/uv sync --frozen",
        ])

    # Step: Sync secrets
    step += 1
    print(f"\n[{step}/{total_steps}] Syncing secrets...")
    if local_env and not dry_run:
        sync_secrets(host, user, local_env, skip_secrets)
    elif dry_run:
        print("  DRY RUN - Secrets not synced")
    else:
        print("  No local .env loaded, skipping")

    # Step: Restart service
    step += 1
    print(f"\n[{step}/{total_steps}] Restarting service...")
    if not dry_run:
        run_ssh(host, user, [
            "systemctl restart winebox",
        ])

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
    parser = argparse.ArgumentParser(
        description="Deploy WineBox to Digital Ocean droplet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Regular deployment (auto-discovers droplet IP from API)
    python deploy/deploy.py

    # First-time setup with DNS
    python deploy/deploy.py --setup-dns

    # Preview what would happen
    python deploy/deploy.py --setup-dns --dry-run

    # Deploy to specific droplet
    python deploy/deploy.py --droplet-name my-droplet

    # Deploy without syncing secrets
    python deploy/deploy.py --no-secrets
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
        "--branch",
        default="main",
        help="Git branch to deploy (default: main)",
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

    # Load .env file
    env_file = Path(__file__).parent.parent / ".env"
    local_env: dict[str, str | None] = {}
    if env_file.exists():
        load_dotenv(env_file)
        local_env = dotenv_values(env_file)

    # Get DO token (needed for IP lookup and DNS)
    do_token = local_env.get("WINEBOX_DO_TOKEN")

    # Get host - try explicit, then env, then API lookup
    host = args.host or os.environ.get("WINEBOX_DROPLET_IP")
    if not host:
        if not do_token:
            print("Error: No host specified and WINEBOX_DO_TOKEN not set.")
            print("Either set WINEBOX_DROPLET_IP or WINEBOX_DO_TOKEN in .env")
            sys.exit(1)

        droplet_name = os.environ.get("WINEBOX_DROPLET_NAME", args.droplet_name)
        print(f"Looking up IP for droplet '{droplet_name}'...")
        host = get_droplet_ip(do_token, droplet_name)
        if not host:
            print(f"Error: Droplet '{droplet_name}' not found.")
            print("Check the droplet name or set WINEBOX_DROPLET_IP in .env")
            sys.exit(1)
        print(f"Found droplet IP: {host}")

    # Get user
    user = os.environ.get("WINEBOX_DROPLET_USER", args.user)

    deploy(
        host=host,
        user=user,
        branch=args.branch,
        local_env=local_env,
        skip_secrets=args.no_secrets,
        setup_dns_flag=args.setup_dns,
        domain=args.domain,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
