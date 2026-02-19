#!/usr/bin/env python3
"""Configure Digital Ocean DNS records for Fastmail email.

This script sets up the required DNS records for using Fastmail
with a domain hosted on Digital Ocean.

Required records:
- MX records (2) for receiving email
- SPF record (TXT) for sender verification
- DKIM records (3 CNAMEs) for email signing
- DMARC record (TXT) for policy

Usage:
    # Add WINEBOX_DO_TOKEN to your .env file, then:
    python setup_digitalocean_fastmail_dns.py --domain winebox.app

To get your Digital Ocean API token:
    https://cloud.digitalocean.com/account/api/tokens
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Fastmail MX records
# Reference: https://www.fastmail.help/hc/en-us/articles/360060591153-Manual-DNS-configuration
FASTMAIL_MX_RECORDS = [
    {"priority": 10, "value": "in1-smtp.messagingengine.com."},
    {"priority": 20, "value": "in2-smtp.messagingengine.com."},
]

# Fastmail SPF record
FASTMAIL_SPF = "v=spf1 include:spf.messagingengine.com ~all"

# Fastmail DKIM CNAME records
FASTMAIL_DKIM_RECORDS = [
    {"name": "fm1._domainkey", "value": "fm1.{domain}.dkim.fmhosted.com."},
    {"name": "fm2._domainkey", "value": "fm2.{domain}.dkim.fmhosted.com."},
    {"name": "fm3._domainkey", "value": "fm3.{domain}.dkim.fmhosted.com."},
]

# DMARC record (relaxed policy to start - change to reject after testing)
DMARC_RECORD = "v=DMARC1; p=none; rua=mailto:dmarc@{domain}"


class DigitalOceanDNS:
    """Digital Ocean DNS API client."""

    BASE_URL = "https://api.digitalocean.com/v2"

    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def get_domain(self, domain: str) -> dict | None:
        """Check if domain exists in Digital Ocean."""
        response = requests.get(
            f"{self.BASE_URL}/domains/{domain}",
            headers=self.headers,
        )
        if response.status_code == 200:
            return response.json()["domain"]
        return None

    def list_records(self, domain: str) -> list[dict]:
        """List all DNS records for a domain."""
        records = []
        page = 1
        while True:
            response = requests.get(
                f"{self.BASE_URL}/domains/{domain}/records",
                headers=self.headers,
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            data = response.json()
            records.extend(data["domain_records"])
            if "pages" not in data.get("links", {}) or "next" not in data["links"]["pages"]:
                break
            page += 1
        return records

    def create_record(self, domain: str, record: dict) -> dict:
        """Create a DNS record."""
        response = requests.post(
            f"{self.BASE_URL}/domains/{domain}/records",
            headers=self.headers,
            json=record,
        )
        response.raise_for_status()
        return response.json()["domain_record"]

    def delete_record(self, domain: str, record_id: int) -> None:
        """Delete a DNS record."""
        response = requests.delete(
            f"{self.BASE_URL}/domains/{domain}/records/{record_id}",
            headers=self.headers,
        )
        response.raise_for_status()


def setup_fastmail_dns(
    token: str,
    domain: str,
    dmarc_email: str | None = None,
    dry_run: bool = False,
) -> None:
    """Set up Fastmail DNS records on Digital Ocean."""
    client = DigitalOceanDNS(token)

    # Check domain exists
    print(f"Checking domain {domain}...")
    if not client.get_domain(domain):
        print(f"Error: Domain '{domain}' not found in Digital Ocean.")
        print("Make sure you've added the domain to Digital Ocean first.")
        sys.exit(1)

    print(f"Domain {domain} found. Fetching existing records...")
    existing_records = client.list_records(domain)

    # Helper to check if record exists
    def record_exists(record_type: str, name: str, data: str | None = None) -> dict | None:
        for r in existing_records:
            if r["type"] == record_type and r["name"] == name:
                if data is None or r["data"] == data:
                    return r
        return None

    # Track changes
    changes = []

    # 1. Set up MX records
    print("\n--- MX Records ---")
    # First, check for conflicting MX records
    existing_mx = [r for r in existing_records if r["type"] == "MX"]
    fastmail_mx_values = {mx["value"] for mx in FASTMAIL_MX_RECORDS}

    for mx in existing_mx:
        if mx["data"] + "." not in fastmail_mx_values and mx["data"] not in fastmail_mx_values:
            print(f"  WARNING: Found non-Fastmail MX record: {mx['data']} (priority {mx['priority']})")
            print(f"           Record ID: {mx['id']} - Consider removing manually if not needed")

    for mx in FASTMAIL_MX_RECORDS:
        # Check if this MX already exists
        mx_value = mx["value"].rstrip(".")
        exists = any(
            r["data"].rstrip(".") == mx_value and r["priority"] == mx["priority"]
            for r in existing_mx
        )
        if exists:
            print(f"  MX {mx['priority']} {mx['value']} - Already exists")
        else:
            print(f"  MX {mx['priority']} {mx['value']} - Will create")
            changes.append({
                "action": "create",
                "record": {
                    "type": "MX",
                    "name": "@",
                    "data": mx["value"],
                    "priority": mx["priority"],
                    "ttl": 3600,
                },
            })

    # 2. Set up SPF record
    print("\n--- SPF Record ---")
    existing_spf = [r for r in existing_records if r["type"] == "TXT" and r["name"] == "@" and "spf" in r["data"].lower()]

    if existing_spf:
        current_spf = existing_spf[0]
        if "spf.messagingengine.com" in current_spf["data"]:
            print(f"  SPF record already includes Fastmail: {current_spf['data']}")
        else:
            print(f"  WARNING: Existing SPF record found: {current_spf['data']}")
            print(f"           You may need to merge it with Fastmail SPF manually")
            print(f"           Recommended: {FASTMAIL_SPF}")
    else:
        print(f"  SPF {FASTMAIL_SPF} - Will create")
        changes.append({
            "action": "create",
            "record": {
                "type": "TXT",
                "name": "@",
                "data": FASTMAIL_SPF,
                "ttl": 3600,
            },
        })

    # 3. Set up DKIM records
    print("\n--- DKIM Records ---")
    # Convert domain for DKIM (replace dots with dashes for subdomain part)
    dkim_domain = domain.replace(".", "-")

    for dkim in FASTMAIL_DKIM_RECORDS:
        dkim_value = dkim["value"].format(domain=dkim_domain)
        existing = record_exists("CNAME", dkim["name"])
        if existing:
            if existing["data"].rstrip(".") == dkim_value.rstrip("."):
                print(f"  CNAME {dkim['name']} -> {dkim_value} - Already exists")
            else:
                print(f"  CNAME {dkim['name']} - EXISTS but points to {existing['data']}")
                print(f"           Expected: {dkim_value}")
        else:
            print(f"  CNAME {dkim['name']} -> {dkim_value} - Will create")
            changes.append({
                "action": "create",
                "record": {
                    "type": "CNAME",
                    "name": dkim["name"],
                    "data": dkim_value,
                    "ttl": 3600,
                },
            })

    # 4. Set up DMARC record
    print("\n--- DMARC Record ---")
    dmarc_email_addr = dmarc_email or f"dmarc@{domain}"
    dmarc_value = DMARC_RECORD.format(domain=dmarc_email_addr.split("@")[1] if "@" in dmarc_email_addr else domain)
    dmarc_value = dmarc_value.replace("{domain}", domain)

    existing_dmarc = record_exists("TXT", "_dmarc")
    if existing_dmarc:
        print(f"  DMARC record already exists: {existing_dmarc['data']}")
    else:
        print(f"  TXT _dmarc -> {dmarc_value} - Will create")
        changes.append({
            "action": "create",
            "record": {
                "type": "TXT",
                "name": "_dmarc",
                "data": dmarc_value,
                "ttl": 3600,
            },
        })

    # Summary and execution
    print(f"\n{'='*50}")
    print(f"Summary: {len(changes)} record(s) to create")

    if not changes:
        print("No changes needed. DNS is already configured for Fastmail.")
        return

    if dry_run:
        print("\nDRY RUN - No changes made.")
        print("Remove --dry-run flag to apply changes.")
        return

    print("\nApplying changes...")
    for change in changes:
        record = change["record"]
        try:
            result = client.create_record(domain, record)
            print(f"  Created {record['type']} record: {record['name']} (ID: {result['id']})")
        except requests.HTTPError as e:
            print(f"  ERROR creating {record['type']} {record['name']}: {e}")
            if e.response is not None:
                print(f"         Response: {e.response.text}")

    print("\nDone! DNS records have been configured.")
    print("\nNext steps:")
    print("1. Wait 5-30 minutes for DNS propagation")
    print("2. Go to Fastmail Settings -> Domains -> Add Domain")
    print("3. Enter your domain and click 'Check Now' to verify")
    print("4. Once verified, consider updating DMARC policy from 'none' to 'quarantine' or 'reject'")


def main():
    parser = argparse.ArgumentParser(
        description="Configure Digital Ocean DNS for Fastmail email",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Add to your .env file:
    WINEBOX_DO_TOKEN=your-api-token-here

    # Dry run (see what would be created):
    python setup_digitalocean_fastmail_dns.py --domain winebox.app --dry-run

    # Apply changes:
    python setup_digitalocean_fastmail_dns.py --domain winebox.app

Environment variables (loaded from .env):
    WINEBOX_DO_TOKEN    - Your Digital Ocean API token
                          Get one at: https://cloud.digitalocean.com/account/api/tokens
""",
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Domain name to configure (e.g., winebox.app)",
    )
    parser.add_argument(
        "--token",
        help="Digital Ocean API token (or set DIGITALOCEAN_TOKEN env var)",
    )
    parser.add_argument(
        "--dmarc-email",
        help="Email address for DMARC reports (default: dmarc@<domain>)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    # Load .env file from current directory or project root
    env_file = Path(".env")
    if not env_file.exists():
        # Try project root (parent of scripts directory)
        env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"Loaded environment from {env_file}")

    # Get token
    token = args.token or os.environ.get("WINEBOX_DO_TOKEN")
    if not token:
        print("Error: Digital Ocean API token required.")
        print("Add WINEBOX_DO_TOKEN to your .env file or use --token flag.")
        print("Get a token at: https://cloud.digitalocean.com/account/api/tokens")
        sys.exit(1)

    setup_fastmail_dns(
        token=token,
        domain=args.domain,
        dmarc_email=args.dmarc_email,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
