"""Admin authentication endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address

from winebox.services.auth import (
    RequireAdmin,
    RequireAuth,
    authenticate_user,
    create_access_token,
    revoke_token,
)

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
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    access_token = create_access_token(data={"sub": user.email})
    logger.info("Admin login: %s", user.email)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def admin_logout(
    current_user: RequireAuth,
    request: Request,
) -> dict:
    """Logout by revoking the current token."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    if token:
        await revoke_token(token, user_id=str(current_user.id), reason="admin_logout")
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
