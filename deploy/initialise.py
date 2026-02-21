#!/usr/bin/env python3
"""Initialise a fresh Digital Ocean droplet for WineBox production.

Combines all setup steps into a single command:
1. Server setup (packages, user, directories, configs)
2. Cloud firewall (ports 22/80/443 via DO API)
3. DNS configuration (A records for @, www, booze)
4. Wait for DNS propagation
5. SSL certificates (certbot --standalone)
6. Start nginx
7. Application deployment
8. X-Wines dataset import (optional)

Usage:
    # Full initialisation
    python -m deploy.initialise --host YOUR_DROPLET_IP

    # Preview without changes
    python -m deploy.initialise --dry-run

    # Skip X-Wines import
    python -m deploy.initialise --skip-xwines
"""

import argparse
import socket
import time

from deploy.app import deploy
from deploy.common import (
    DigitalOceanAPI,
    get_env_config,
    resolve_host,
    run_ssh,
)
from deploy.setup import setup
from deploy.xwines import deploy_xwines


# =============================================================================
# DNS Setup
# =============================================================================

def setup_all_dns_records(
    token: str,
    droplet_ip: str,
    dry_run: bool = False,
) -> None:
    """Create/update A records for @, www, and booze on winebox.app.

    Args:
        token: Digital Ocean API token
        droplet_ip: IP address to point records to
        dry_run: If True, preview without applying
    """
    client = DigitalOceanAPI(token)
    domain = "winebox.app"

    print(f"Configuring DNS for {domain} -> {droplet_ip}")

    existing_records = client.list_dns_records(domain)

    a_records = [
        {"name": "@", "description": "Root domain"},
        {"name": "www", "description": "WWW subdomain"},
        {"name": "booze", "description": "App subdomain"},
    ]

    for record_info in a_records:
        name = record_info["name"]

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
# Cloud Firewall
# =============================================================================

def setup_cloud_firewall(
    token: str,
    droplet_ip: str,
    dry_run: bool = False,
) -> None:
    """Ensure DO cloud firewall allows ports 22, 80, 443 inbound.

    Finds an existing "Winebox" firewall by name and updates it,
    or creates a new one if none exists.

    Args:
        token: Digital Ocean API token
        droplet_ip: Droplet IP (used to find droplet ID for assignment)
        dry_run: If True, preview without applying
    """
    client = DigitalOceanAPI(token)

    print("Configuring cloud firewall...")

    # Find the droplet ID from IP
    droplet_id = None
    for droplet in client.list_droplets():
        for network in droplet["networks"]["v4"]:
            if network["type"] == "public" and network["ip_address"] == droplet_ip:
                droplet_id = droplet["id"]
                break
        if droplet_id:
            break

    if not droplet_id:
        print(f"  Warning: Could not find droplet with IP {droplet_ip}")
        print("  Skipping cloud firewall setup")
        return

    inbound_rules = [
        {
            "protocol": "tcp",
            "ports": "22",
            "sources": {"addresses": ["0.0.0.0/0", "::/0"]},
        },
        {
            "protocol": "tcp",
            "ports": "80",
            "sources": {"addresses": ["0.0.0.0/0", "::/0"]},
        },
        {
            "protocol": "tcp",
            "ports": "443",
            "sources": {"addresses": ["0.0.0.0/0", "::/0"]},
        },
    ]

    outbound_rules = [
        {
            "protocol": "tcp",
            "ports": "all",
            "destinations": {"addresses": ["0.0.0.0/0", "::/0"]},
        },
        {
            "protocol": "udp",
            "ports": "all",
            "destinations": {"addresses": ["0.0.0.0/0", "::/0"]},
        },
        {
            "protocol": "icmp",
            "ports": "0",
            "destinations": {"addresses": ["0.0.0.0/0", "::/0"]},
        },
    ]

    firewall_data = {
        "name": "Winebox",
        "inbound_rules": inbound_rules,
        "outbound_rules": outbound_rules,
        "droplet_ids": [droplet_id],
    }

    # Check for existing firewall
    existing_firewalls = client.list_firewalls()
    existing = next(
        (fw for fw in existing_firewalls if fw["name"] == "Winebox"),
        None,
    )

    if existing:
        print(f"  Found existing firewall: {existing['id']}")
        # Ensure droplet is assigned
        existing_ids = [d for d in existing.get("droplet_ids", [])]
        if droplet_id not in existing_ids:
            existing_ids.append(droplet_id)
        firewall_data["droplet_ids"] = existing_ids

        if dry_run:
            print("  DRY RUN - Would update firewall rules")
        else:
            client.update_firewall(existing["id"], firewall_data)
            print("  Firewall updated with inbound rules: 22, 80, 443")
    else:
        print("  Creating new firewall...")
        if dry_run:
            print("  DRY RUN - Would create firewall 'Winebox'")
        else:
            fw = client.create_firewall(firewall_data)
            print(f"  Firewall created: {fw['id']}")
            print("  Inbound rules: 22, 80, 443")


# =============================================================================
# DNS Propagation
# =============================================================================

def wait_for_dns_propagation(
    domains: list[str],
    expected_ip: str,
    timeout: int = 600,
    interval: int = 15,
) -> bool:
    """Wait until all domains resolve to the expected IP.

    Args:
        domains: List of domain names to check
        expected_ip: Expected IP address
        timeout: Maximum wait time in seconds
        interval: Polling interval in seconds

    Returns:
        True if all domains resolved, False if timed out
    """
    print(f"Waiting for DNS propagation (timeout: {timeout}s)...")
    start = time.time()

    while time.time() - start < timeout:
        all_resolved = True
        for domain in domains:
            try:
                results = socket.getaddrinfo(domain, None, socket.AF_INET)
                resolved_ips = {r[4][0] for r in results}
                if expected_ip in resolved_ips:
                    print(f"  {domain} -> {expected_ip} (resolved)")
                else:
                    print(f"  {domain} -> {resolved_ips} (waiting for {expected_ip})")
                    all_resolved = False
            except socket.gaierror:
                print(f"  {domain} -> (not resolving yet)")
                all_resolved = False

        if all_resolved:
            print("  All domains resolved!")
            return True

        elapsed = int(time.time() - start)
        print(f"  Waiting {interval}s... ({elapsed}s elapsed)")
        time.sleep(interval)

    print(f"  Timed out after {timeout}s")
    return False


# =============================================================================
# SSL Certificates
# =============================================================================

def setup_ssl_certificates(
    host: str,
    user: str,
    dry_run: bool = False,
) -> bool:
    """Set up SSL certificates using certbot standalone mode.

    Stops nginx (port 80 must be free), runs certbot, then starts nginx.

    Args:
        host: Droplet IP or hostname
        user: SSH username
        dry_run: If True, preview without applying

    Returns:
        True if successful, False otherwise
    """
    print("Setting up SSL certificates...")

    if dry_run:
        print("  DRY RUN - Would run certbot for:")
        print("    - winebox.app, www.winebox.app")
        print("    - booze.winebox.app")
        return True

    # Stop nginx to free port 80 for standalone mode
    print("  Stopping nginx for certbot standalone mode...")
    run_ssh(host, user, "systemctl stop nginx", check=False)

    success = True

    # Certificate for root + www
    print("  Requesting certificate for winebox.app + www.winebox.app...")
    result = run_ssh(
        host, user,
        "certbot certonly --standalone --non-interactive --agree-tos "
        "--email support@winebox.app -d winebox.app -d www.winebox.app",
        check=False, capture=True,
    )
    if "successfully" in result.lower() or "certificate not yet due for renewal" in result.lower():
        print("  Certificate obtained for winebox.app")
    else:
        print(f"  Warning: certbot for winebox.app may have failed:")
        print(f"    {result[:200]}")
        success = False

    # Certificate for booze subdomain
    print("  Requesting certificate for booze.winebox.app...")
    result = run_ssh(
        host, user,
        "certbot certonly --standalone --non-interactive --agree-tos "
        "--email support@winebox.app -d booze.winebox.app",
        check=False, capture=True,
    )
    if "successfully" in result.lower() or "certificate not yet due for renewal" in result.lower():
        print("  Certificate obtained for booze.winebox.app")
    else:
        print(f"  Warning: certbot for booze.winebox.app may have failed:")
        print(f"    {result[:200]}")
        success = False

    # Start nginx back up
    print("  Starting nginx...")
    run_ssh(host, user, "systemctl start nginx")

    if not success:
        print("\n  SSL certificate setup had issues. You may need to run manually:")
        print(f"    ssh {user}@{host} 'systemctl stop nginx'")
        print(f"    ssh {user}@{host} 'certbot certonly --standalone -d winebox.app -d www.winebox.app'")
        print(f"    ssh {user}@{host} 'certbot certonly --standalone -d booze.winebox.app'")
        print(f"    ssh {user}@{host} 'systemctl start nginx'")

    return success


# =============================================================================
# Main Orchestrator
# =============================================================================

def step_header(step_num: int, total: int, message: str) -> None:
    """Print a step header."""
    print(f"\n{'='*60}")
    print(f"  [{step_num}/{total}] {message}")
    print(f"{'='*60}")


def initialise_droplet(
    host: str,
    user: str,
    domain: str,
    do_token: str | None,
    env_values: dict[str, str | None],
    version: str | None = None,
    skip_xwines: bool = False,
    dry_run: bool = False,
) -> None:
    """Initialise a fresh droplet with full WineBox production stack.

    Sequences: setup -> cloud firewall -> DNS -> DNS propagation ->
    SSL certs -> nginx -> app deploy -> X-Wines import.

    Args:
        host: Droplet IP address
        user: SSH username
        domain: Application domain (e.g. booze.winebox.app)
        do_token: Digital Ocean API token (required for DNS/firewall)
        env_values: Local .env values for secrets sync
        version: WineBox version to install (None for latest)
        skip_xwines: Skip X-Wines dataset import
        dry_run: Preview without applying
    """
    total_steps = 7 if skip_xwines else 8

    print(f"Initialising WineBox on {host}...")
    print(f"Domain: {domain}")
    if dry_run:
        print("MODE: DRY RUN")
    print("=" * 60)

    # Step 1: Server setup
    step_header(1, total_steps, "Server setup (packages, user, configs)")
    if dry_run:
        print("  DRY RUN - Would run deploy.setup.setup()")
    else:
        setup(host=host, user=user, domain=domain)

    # Step 2: Cloud firewall
    step_header(2, total_steps, "Cloud firewall (ports 22, 80, 443)")
    if do_token:
        setup_cloud_firewall(do_token, host, dry_run=dry_run)
    else:
        print("  Warning: WINEBOX_DO_TOKEN not set, skipping cloud firewall")
        print("  Ensure ports 22, 80, 443 are open in your DO dashboard")

    # Step 3: DNS configuration
    step_header(3, total_steps, "DNS configuration (A records)")
    if do_token:
        setup_all_dns_records(do_token, host, dry_run=dry_run)
    else:
        print("  Warning: WINEBOX_DO_TOKEN not set, skipping DNS setup")
        print("  Configure DNS manually in your DO dashboard")

    # Step 4: Wait for DNS propagation
    step_header(4, total_steps, "Waiting for DNS propagation")
    if dry_run:
        print("  DRY RUN - Would wait for DNS propagation")
    elif do_token:
        domains = ["winebox.app", "www.winebox.app", "booze.winebox.app"]
        resolved = wait_for_dns_propagation(domains, host)
        if not resolved:
            print("  DNS hasn't fully propagated yet.")
            print("  Continuing anyway - SSL may fail if DNS isn't ready.")
    else:
        print("  Skipping DNS wait (no DNS changes made)")

    # Step 5: SSL certificates
    step_header(5, total_steps, "SSL certificates (certbot)")
    ssl_ok = setup_ssl_certificates(host, user, dry_run=dry_run)
    if not ssl_ok and not dry_run:
        print("  Warning: SSL setup had issues but continuing...")

    # Step 6: Restart nginx
    step_header(6, total_steps, "Start nginx")
    if dry_run:
        print("  DRY RUN - Would restart nginx")
    else:
        run_ssh(host, user, "systemctl restart nginx")
        result = run_ssh(host, user, "systemctl is-active nginx", check=False, capture=True)
        if "active" in result:
            print("  nginx is running")
        else:
            print("  Warning: nginx may not be running correctly")

    # Step 7: Application deployment
    step_header(7, total_steps, "Application deployment")
    if dry_run:
        print("  DRY RUN - Would run deploy.app.deploy()")
    else:
        deploy(
            host=host,
            user=user,
            version=version,
            env_values=env_values,
            domain=domain,
        )

    # Step 8: X-Wines import (optional)
    if not skip_xwines:
        step_header(8, total_steps, "X-Wines dataset import")
        if dry_run:
            print("  DRY RUN - Would run deploy.xwines.deploy_xwines()")
        else:
            deploy_xwines(host=host, user=user, dry_run=dry_run)

    # Summary
    print(f"\n{'='*60}")
    if dry_run:
        print("DRY RUN complete - no changes made")
    else:
        print("Droplet initialisation complete!")
        print(f"\nURLs:")
        print(f"  Landing page: https://winebox.app")
        print(f"  Application:  https://{domain}")
        if not ssl_ok:
            print(f"\nNote: SSL had issues - check certificates manually")
    print(f"{'='*60}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Initialise a fresh DO droplet for WineBox production",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Full initialisation
    python -m deploy.initialise --host 1.2.3.4

    # Preview without changes
    python -m deploy.initialise --dry-run

    # Skip X-Wines dataset import
    python -m deploy.initialise --skip-xwines

    # Specific version
    python -m deploy.initialise --version 0.5.6
""",
    )
    parser.add_argument(
        "--host",
        help="Droplet IP (or set WINEBOX_DROPLET_IP in .env)",
    )
    parser.add_argument(
        "--user",
        default="root",
        help="SSH user (default: root)",
    )
    parser.add_argument(
        "--domain",
        default="booze.winebox.app",
        help="App domain (default: booze.winebox.app)",
    )
    parser.add_argument(
        "--droplet-name",
        default="winebox-droplet",
        help="Droplet name for IP lookup (default: winebox-droplet)",
    )
    parser.add_argument(
        "--version",
        help="WineBox version to install (default: latest)",
    )
    parser.add_argument(
        "--skip-xwines",
        action="store_true",
        help="Skip X-Wines dataset import",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying",
    )

    args = parser.parse_args()

    config = get_env_config(
        host=args.host,
        user=args.user,
        droplet_name=args.droplet_name,
        domain=args.domain,
    )

    host = resolve_host(config)

    initialise_droplet(
        host=host,
        user=config.user,
        domain=config.domain,
        do_token=config.do_token,
        env_values=config.env_values,
        version=args.version,
        skip_xwines=args.skip_xwines,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
