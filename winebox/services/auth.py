"""Authentication dependencies — adapters from regstack to WineBox.

regstack owns user records, JWT signing/validation, password hashing,
session blacklist, and login lockout. This module exposes the small
public surface WineBox routers depend on:

- `RequireAuth` / `RequireAdmin` / `CurrentUser` FastAPI dependency
  aliases that resolve to a `winebox.models.user.User` (MongoDocument).
  We re-fetch via the WineBox User class so downstream queries keyed
  on `owner_id` (ObjectId) work — regstack's BaseUser exposes `.id`
  as a string.
- `get_password_hash()` — Argon2id hash via regstack's hasher, used
  by admin endpoints that create users out-of-band.
"""

from __future__ import annotations

import logging
from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from regstack.auth.password import PasswordHasher
from regstack.models.user import BaseUser

from winebox.auth.regstack_setup import get_regstack
from winebox.models.user import User

security_logger = logging.getLogger("winebox.security")

# Standalone hasher for utility callers (CLI, admin create-user). Argon2id
# parameters are pinned by regstack's hasher; we use a fresh instance here
# so callers don't need the full RegStack singleton booted.
_password_hasher = PasswordHasher()

_bearer = HTTPBearer(auto_error=False)


def get_password_hash(password: str) -> str:
    """Argon2id hash of the supplied password."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time check that `plain_password` matches `hashed_password`."""
    return _password_hasher.verify(plain_password, hashed_password)


async def _fetch_winebox_user(rs_user: BaseUser) -> User:
    """Re-fetch the WineBox MongoDocument User for the authenticated principal.

    regstack returns its own `BaseUser` Pydantic model with `id` as a
    string. WineBox's domain code keys on `owner_id` (ObjectId) so we
    swap in the MongoDocument-backed User, which also lets routes
    that hold the user perform `.save()` etc. without an extra import.
    """
    if rs_user.id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user has no id",
        )
    try:
        oid = ObjectId(rs_user.id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user has an invalid id",
        )
    user = await User.find_one({"_id": oid})
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


async def require_auth(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """FastAPI dependency: authenticated user as a WineBox MongoDocument.

    Delegates JWT decode, blacklist check, and bulk-revoke check to
    regstack's bound `current_user()` dependency, then re-fetches the
    same record via the WineBox `User` model so callers get a
    MongoDocument with `.id` as ObjectId.
    """
    rs = get_regstack()
    rs_dep = rs.deps.current_user()
    rs_user: BaseUser = await rs_dep(request, creds)
    return await _fetch_winebox_user(rs_user)


async def require_admin(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """FastAPI dependency: authenticated admin user as a WineBox MongoDocument."""
    rs = get_regstack()
    rs_dep = rs.deps.current_admin()
    rs_user: BaseUser = await rs_dep(request, creds)
    return await _fetch_winebox_user(rs_user)


async def current_user_optional(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    """FastAPI dependency: returns None when no/invalid bearer token is supplied.

    For routes that allow anonymous access — wraps `require_auth` and
    swallows the 401 that regstack raises on missing or bad credentials.
    """
    if creds is None:
        return None
    try:
        return await require_auth(request, creds)
    except HTTPException:
        return None


CurrentUser = Annotated[User | None, Depends(current_user_optional)]
RequireAuth = Annotated[User, Depends(require_auth)]
RequireAdmin = Annotated[User, Depends(require_admin)]
