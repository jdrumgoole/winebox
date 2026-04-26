"""Verify email DNS records (MX, SPF, DKIM, DMARC) for winebox.app.

Checks that all required records resolve correctly and reports any issues.
Designed to run weekly via a scheduled task.

Usage:
    uv run python scripts/check_email_dns.py
    uv run python scripts/check_email_dns.py --domain winebox.app
"""

import argparse
import signal
import subprocess
import sys


def handle_sigint(sig: int, frame: object) -> None:
    print("\nAborted.")
    sys.exit(130)


signal.signal(signal.SIGINT, handle_sigint)

DOMAIN = "winebox.app"

EXPECTED_MX = [
    "in1-smtp.messagingengine.com.",
    "in2-smtp.messagingengine.com.",
]

EXPECTED_DKIM_CNAMES = {
    "fm1._domainkey": "fm1.{domain}.dkim.fmhosted.com.",
    "fm2._domainkey": "fm2.{domain}.dkim.fmhosted.com.",
    "fm3._domainkey": "fm3.{domain}.dkim.fmhosted.com.",
}

EXPECTED_SPF_INCLUDES = [
    "spf.messagingengine.com",
]


def dig(record_type: str, name: str) -> list[str]:
    """Run dig and return the short answers."""
    try:
        result = subprocess.run(
            ["dig", "+short", record_type, name],
            capture_output=True, text=True, timeout=10,
        )
        return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def check_mx(domain: str) -> list[str]:
    """Check MX records."""
    errors = []
    records = dig("MX", domain)
    # MX records come as "priority hostname"
    mx_hosts = [r.split()[-1] if " " in r else r for r in records]

    for expected in EXPECTED_MX:
        if expected not in mx_hosts:
            errors.append(f"MX: missing {expected}")

    if not errors:
        print(f"  MX: OK ({len(mx_hosts)} records)")
    return errors


def check_spf(domain: str) -> list[str]:
    """Check SPF record."""
    errors = []
    records = dig("TXT", domain)
    spf_records = [r.strip('"') for r in records if "v=spf1" in r]

    if not spf_records:
        errors.append("SPF: no SPF record found")
        return errors

    spf = spf_records[0]
    for include in EXPECTED_SPF_INCLUDES:
        if include not in spf:
            errors.append(f"SPF: missing include:{include}")

    if not errors:
        print(f"  SPF: OK")
    return errors


def check_dkim(domain: str) -> list[str]:
    """Check DKIM CNAME records and that they resolve to TXT keys."""
    errors = []

    for host, expected_target_template in EXPECTED_DKIM_CNAMES.items():
        expected_target = expected_target_template.format(domain=domain)
        fqdn = f"{host}.{domain}"

        cname_records = dig("CNAME", fqdn)
        if not cname_records:
            errors.append(f"DKIM: {fqdn} — no CNAME record")
            continue

        actual = cname_records[0]
        if actual != expected_target:
            errors.append(f"DKIM: {fqdn} — points to {actual}, expected {expected_target}")
            continue

        # Verify the CNAME target resolves to a TXT record with a DKIM key
        txt_records = dig("TXT", fqdn)
        has_key = any("v=DKIM1" in r for r in txt_records)
        if not has_key:
            errors.append(f"DKIM: {fqdn} — CNAME correct but no DKIM key resolves (may need propagation time)")
            continue

    if not errors:
        print(f"  DKIM: OK (3 keys)")
    return errors


def check_dmarc(domain: str) -> list[str]:
    """Check DMARC record."""
    errors = []
    records = dig("TXT", f"_dmarc.{domain}")
    dmarc_records = [r.strip('"') for r in records if "v=DMARC1" in r]

    if not dmarc_records:
        errors.append("DMARC: no DMARC record found")
        return errors

    print(f"  DMARC: OK")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check email DNS records.")
    parser.add_argument("--domain", default=DOMAIN, help=f"Domain to check (default: {DOMAIN})")
    args = parser.parse_args()

    domain = args.domain
    print(f"Checking email DNS for {domain}...")

    all_errors: list[str] = []
    all_errors.extend(check_mx(domain))
    all_errors.extend(check_spf(domain))
    all_errors.extend(check_dkim(domain))
    all_errors.extend(check_dmarc(domain))

    if all_errors:
        print(f"\n{len(all_errors)} issue(s) found:")
        for error in all_errors:
            print(f"  ✗ {error}")
        return 1

    print(f"\nAll email DNS records OK for {domain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
