"""Check Let's Encrypt cert expiry for the WineBox public hostnames.

Connects to each host on port 443, pulls the leaf cert, and reports days
until expiry. Exits non-zero if any cert is already expired or expires
within `--warn-days` (default 14) — small enough that certbot's auto-renew
should have fired well before the warning window.

Designed for the weekly GitHub Action; can also be run by hand:

    uv run python scripts/check_certs.py
    uv run python scripts/check_certs.py --warn-days 21
    uv run python scripts/check_certs.py --hosts oat.winebox.app
"""

from __future__ import annotations

import argparse
import socket
import ssl
import sys
from datetime import datetime, timezone

DEFAULT_HOSTS: tuple[str, ...] = (
    "booze.winebox.app",
    "oat.winebox.app",
    "oatadmin.winebox.app",
)
DEFAULT_WARN_DAYS = 14


def fetch_cert_not_after(host: str, port: int = 443, timeout: float = 10.0) -> datetime:
    """Connect to host:port, complete the TLS handshake, and return the
    leaf cert's notAfter as a timezone-aware UTC datetime.

    Uses the system trust store via `ssl.create_default_context()` so a
    self-signed or wrong-host cert raises rather than silently passing.
    """
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            cert = tls.getpeercert()
    if not cert or "notAfter" not in cert:
        raise RuntimeError(f"{host}: peer cert had no notAfter field")
    # OpenSSL formats notAfter as e.g. "Jul 25 03:42:11 2026 GMT".
    not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
    return not_after.replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--hosts",
        nargs="+",
        default=list(DEFAULT_HOSTS),
        help="Hostnames to check (default: all WineBox public hosts).",
    )
    parser.add_argument(
        "--warn-days",
        type=int,
        default=DEFAULT_WARN_DAYS,
        help=f"Fail if a cert expires within this many days (default: {DEFAULT_WARN_DAYS}).",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    failures: list[str] = []

    for host in args.hosts:
        try:
            not_after = fetch_cert_not_after(host)
        except Exception as exc:  # network, TLS, or parse error
            print(f"ERROR  {host}: {exc}")
            failures.append(f"{host}: {exc}")
            continue

        days_left = (not_after - now).days
        status = "OK   "
        if days_left < 0:
            status = "EXPIRED"
            failures.append(f"{host}: expired {-days_left} days ago")
        elif days_left < args.warn_days:
            status = "WARN "
            failures.append(
                f"{host}: expires in {days_left} days "
                f"(threshold: {args.warn_days})"
            )
        print(f"{status} {host}: expires {not_after.isoformat()} ({days_left} days)")

    if failures:
        print()
        print("FAIL — cert check found issues:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print()
    print(f"OK — all {len(args.hosts)} cert(s) valid for >= {args.warn_days} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
