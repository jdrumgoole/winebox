"""Authentication endpoints with fastapi-users integration."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from winebox.auth import (
    UserCreate,
    UserRead,
    UserUpdate,
    auth_backend,
    fastapi_users,
)
from winebox.config import settings
from winebox.models.user import User
from winebox.services.analytics import posthog_service
from winebox.services.auth import (
    RequireAuth,
    verify_password,
    get_password_hash,
    authenticate_user,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter()

# Rate limiter for auth endpoints (stricter than global limit)
limiter = Limiter(key_func=get_remote_address)


# ============================================================================
# FastAPI-Users Router Integration
# ============================================================================

# Login endpoint (POST /api/auth/login)
router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="",
)

# Registration endpoint (POST /api/auth/register)
if settings.registration_enabled:
    router.include_router(
        fastapi_users.get_register_router(UserRead, UserCreate),
        prefix="",
    )

# Password reset endpoints (POST /api/auth/forgot-password, /api/auth/reset-password)
router.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="",
)

# Email verification endpoints (POST /api/auth/request-verify-token, /api/auth/verify)
if settings.email_verification_required:
    router.include_router(
        fastapi_users.get_verify_router(UserRead),
        prefix="",
    )


# ============================================================================
# Custom Endpoints (kept for backward compatibility)
# ============================================================================


class UserResponse(BaseModel):
    """User response model for custom endpoints."""

    id: str
    email: str
    full_name: str | None
    is_active: bool
    is_admin: bool
    is_verified: bool
    created_at: datetime
    last_login: datetime | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        """Create UserResponse from User model."""
        return cls(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_admin=user.is_admin,
            is_verified=user.is_verified,
            created_at=user.created_at,
            last_login=user.last_login,
        )


class PasswordChangeRequest(BaseModel):
    """Password change request model."""

    current_password: str
    new_password: str


class Token(BaseModel):
    """Token response model."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60  # seconds


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: RequireAuth,
) -> UserResponse:
    """Get the current authenticated user's information."""
    return UserResponse.from_user(current_user)


@router.put("/password")
@limiter.limit("5/minute;20/hour")  # Rate limiting for password changes
async def change_password(
    request: Request,  # Required for rate limiting
    password_request: PasswordChangeRequest,
    current_user: RequireAuth,
) -> dict:
    """Change the current user's password.

    After changing the password, the current session token is revoked
    and the user must log in again with the new password.
    """
    import logging
    from winebox.services.auth import revoke_token

    security_logger = logging.getLogger("winebox.security")

    # Verify current password
    if not verify_password(password_request.current_password, current_user.hashed_password):
        security_logger.warning(
            "Password change failed - invalid current password: user_id=%s, ip=%s",
            str(current_user.id),
            get_remote_address(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password using Beanie
    current_user.hashed_password = get_password_hash(password_request.new_password)
    current_user.updated_at = datetime.now(timezone.utc)
    await current_user.save()

    # Revoke current token to force re-login with new password
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        await revoke_token(
            token=token,
            user_id=str(current_user.id),
            reason="password_change",
        )

    security_logger.info(
        "Password changed successfully: user_id=%s, ip=%s",
        str(current_user.id),
        get_remote_address(request),
    )

    return {"message": "Password updated successfully. Please log in again."}


@router.post("/logout")
async def logout(
    request: Request,
    current_user: RequireAuth,
) -> dict:
    """Logout the current user by revoking their token.

    The token is added to a blacklist so it cannot be used again.
    """
    from winebox.services.auth import revoke_token

    # Extract token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if token:
        success = await revoke_token(
            token=token,
            user_id=str(current_user.id),
            reason="logout",
        )

        # Track logout event
        posthog_service.capture(
            distinct_id=str(current_user.id),
            event="user_logout",
        )

        if success:
            return {"message": "Successfully logged out"}
        else:
            return {"message": "Logged out (token could not be revoked)"}

    # Track logout event even if no token
    posthog_service.capture(
        distinct_id=str(current_user.id),
        event="user_logout",
    )

    return {"message": "Successfully logged out"}


@router.post("/token", response_model=Token)
@limiter.limit("30/minute;200/hour")  # Rate limiting for login attempts
async def login_token(
    request: Request,  # Required for rate limiting
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """Login with email and password to get an access token.

    This is the legacy endpoint kept for backward compatibility.
    New clients should use POST /api/auth/login instead.

    Note: OAuth2 spec uses 'username' field name, but we accept email here.
    """
    # Get client IP for security logging
    ip_address = get_remote_address(request)

    # authenticate_user now raises HTTPException if account is locked
    user = await authenticate_user(form_data.username, form_data.password, ip_address)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is verified (if verification is required)
    if settings.email_verification_required and not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email not verified. Please check your email for verification link.",
        )

    # Update last login time
    user.last_login = datetime.now(timezone.utc)
    await user.save()

    # Create access token with email as subject
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    # Track login event
    posthog_service.capture(
        distinct_id=str(user.id),
        event="user_login",
        properties={"method": "password"},
    )

    return Token(access_token=access_token)
