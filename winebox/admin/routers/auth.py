"""Admin panel authentication endpoints.

The admin panel runs as a separate FastAPI app on a different port; it
shares the regstack-managed user collection with the main app. These
endpoints are admin-only and reject non-superuser logins outright.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address

from winebox.auth.regstack_setup import get_regstack
from winebox.services.auth import RequireAdmin, RequireAuth

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/login")
@limiter.limit("5/minute")
async def admin_login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> dict:
    """Authenticate an admin user. Rejects non-admin users with 403."""
    rs = get_regstack()
    decision = await rs.lockout.check(form_data.username)
    if decision.locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many failed attempts. "
                f"Try again in {decision.retry_after_seconds} seconds."
            ),
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    user = await rs.users.get_by_email(form_data.username)
    if (
        user is None
        or user.id is None
        or user.hashed_password is None
        or not rs.password_hasher.verify(form_data.password, user.hashed_password)
        or not user.is_active
    ):
        await rs.lockout.record_failure(form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

    await rs.lockout.clear(form_data.username)
    token, _ = rs.jwt.encode(str(user.id), purpose="session")
    logger.info("Admin login: %s", user.email)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/logout")
async def admin_logout(
    current_user: RequireAuth,
    request: Request,
) -> dict:
    """Logout by revoking the current token."""
    rs = get_regstack()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    if token:
        try:
            payload = rs.jwt.decode(token)
            await rs.blacklist.revoke(payload.jti, payload.exp)
        except Exception:
            logger.warning("Admin logout: could not revoke token (decode failed)")
    return {"status": "logged_out"}


@router.get("/me")
async def admin_me(current_user: RequireAdmin) -> dict:
    """Get current admin user info."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_superuser": current_user.is_superuser,
    }
