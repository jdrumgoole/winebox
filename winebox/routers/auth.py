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
    has_api_key: bool
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
            has_api_key=user.anthropic_api_key is not None,
            created_at=user.created_at,
            last_login=user.last_login,
        )


class PasswordChangeRequest(BaseModel):
    """Password change request model."""

    current_password: str
    new_password: str


class ProfileUpdateRequest(BaseModel):
    """Profile update request model."""

    full_name: str | None = None


class ApiKeyUpdateRequest(BaseModel):
    """API key update request model."""

    api_key: str


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
async def change_password(
    request: PasswordChangeRequest,
    current_user: RequireAuth,
) -> dict:
    """Change the current user's password."""
    # Verify current password
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password using Beanie
    current_user.hashed_password = get_password_hash(request.new_password)
    current_user.updated_at = datetime.utcnow()
    await current_user.save()

    return {"message": "Password updated successfully"}


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    request: ProfileUpdateRequest,
    current_user: RequireAuth,
) -> UserResponse:
    """Update the current user's profile."""
    if request.full_name is not None:
        current_user.full_name = request.full_name

    current_user.updated_at = datetime.utcnow()
    await current_user.save()

    return UserResponse.from_user(current_user)


@router.put("/api-key")
async def update_api_key(
    request: ApiKeyUpdateRequest,
    current_user: RequireAuth,
) -> dict:
    """Update the current user's Anthropic API key.

    Note: The API key is stored encrypted and cannot be retrieved after setting.
    """
    current_user.set_encrypted_api_key(request.api_key)
    current_user.updated_at = datetime.utcnow()
    await current_user.save()

    return {"message": "API key updated successfully"}


@router.delete("/api-key")
async def delete_api_key(
    current_user: RequireAuth,
) -> dict:
    """Delete the current user's Anthropic API key."""
    current_user.anthropic_api_key = None
    current_user.updated_at = datetime.utcnow()
    await current_user.save()

    return {"message": "API key deleted successfully"}


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
        if success:
            return {"message": "Successfully logged out"}
        else:
            return {"message": "Logged out (token could not be revoked)"}

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
    user = await authenticate_user(form_data.username, form_data.password)
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

    return Token(access_token=access_token)
