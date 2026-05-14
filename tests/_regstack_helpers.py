"""Test helpers for working with the embedded regstack instance.

regstack signs session tokens with a derived key, so tests can't forge
their own JWTs by reaching for jwt.encode. Use these helpers to mint
tokens identical to those minted by `/api/auth/login`.
"""

from __future__ import annotations

from typing import Any

from winebox.auth.regstack_setup import get_regstack


async def create_access_token(data: dict[str, Any]) -> str:
    """Forge a regstack-signed session token for the test user identified
    in `data["sub"]`.

    The legacy WineBox helper accepted an email as `sub`; regstack signs
    tokens whose `sub` is the user_id. We resolve the email to the
    user_id so existing call sites keep working with no shape change.
    """
    rs = get_regstack()
    subject = data["sub"]
    user = await rs.users.get_by_email(subject)
    if user is None or user.id is None:
        raise ValueError(f"No user found for {subject!r}")
    token, _ = rs.jwt.encode(str(user.id), purpose="session")
    return token
