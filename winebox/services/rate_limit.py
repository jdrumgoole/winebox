"""Shared slowapi limiter factory and pagination caps.

Centralises the env-var gate so every Limiter in the codebase respects
`WINEBOX_RATE_LIMIT_DISABLED=1`. CI runs many concurrent requests from a
single test-client IP and would otherwise trip the per-IP buckets.
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address


# Maximum value of `?limit=` accepted on user-facing list endpoints.
# Defends against a client requesting `limit=10_000_000` and forcing the
# server to load and serialise an arbitrary number of documents.
MAX_PAGE_SIZE = 200

# Hard ceiling for materialising a per-user collection into memory inside a
# request handler. Picked far above any realistic personal cellar size
# (~ tens of bottles up to a few thousand) but low enough to bound memory
# even if the data shape grows or a misbehaving client triggers a worst case.
MAX_USER_RESULTSET = 10_000

# Hard ceiling for materialising a slice of a *reference* collection
# (X-Wines, ~150K wines) inside a request handler. Set above the largest
# expected pagination depth but well under the full dataset so a wildcard
# query cannot drag the whole thing into memory.
MAX_REFERENCE_RESULTSET = 5_000


def _enabled() -> bool:
    return os.environ.get("WINEBOX_RATE_LIMIT_DISABLED", "").lower() not in ("1", "true")


def make_limiter(default_limits: list[str] | None = None) -> Limiter:
    """Create a slowapi `Limiter` that honours `WINEBOX_RATE_LIMIT_DISABLED`."""
    return Limiter(
        key_func=get_remote_address,
        default_limits=default_limits or [],
        enabled=_enabled(),
    )
