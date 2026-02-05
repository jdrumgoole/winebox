"""Authentication endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from winebox.config import settings
from winebox.database import get_db
from winebox.models.user import User
from winebox.services.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_user,
    create_access_token,
    get_current_user,
    get_password_hash,
    require_auth,
    verify_password,
    CurrentUser,
    RequireAuth,
)

router = APIRouter()

# Rate limiter for auth endpoints (stricter than global limit)
limiter = Limiter(key_func=get_remote_address)


class Token(BaseModel):
    """Token response model."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60  # seconds


class UserResponse(BaseModel):
    """User response model."""

    id: str
    username: str
    email: str | None
    full_name: str | None
    is_active: bool
    is_admin: bool
    has_api_key: bool
    created_at: datetime
    last_login: datetime | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user: "User") -> "UserResponse":
        """Create UserResponse from User model."""
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_admin=user.is_admin,
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


@router.post("/token", response_model=Token)
@limiter.limit(f"{settings.auth_rate_limit_per_minute}/minute")
async def login(
    request: Request,  # Required for rate limiting
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Login with username and password to get an access token.

    Rate limited to prevent brute force attacks.
    """
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login time
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    # Create access token
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return Token(access_token=access_token)


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
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Change the current user's password."""
    # Verify current password
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password
    current_user.hashed_password = get_password_hash(request.new_password)
    await db.commit()

    return {"message": "Password updated successfully"}


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    request: ProfileUpdateRequest,
    current_user: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Update the current user's profile."""
    if request.full_name is not None:
        current_user.full_name = request.full_name

    await db.commit()
    await db.refresh(current_user)

    return UserResponse.from_user(current_user)


@router.put("/api-key")
async def update_api_key(
    request: ApiKeyUpdateRequest,
    current_user: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Update the current user's Anthropic API key.

    Note: The API key is stored but cannot be retrieved after setting.
    """
    current_user.anthropic_api_key = request.api_key
    await db.commit()

    return {"message": "API key updated successfully"}


@router.delete("/api-key")
async def delete_api_key(
    current_user: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Delete the current user's Anthropic API key."""
    current_user.anthropic_api_key = None
    await db.commit()

    return {"message": "API key deleted successfully"}


@router.post("/logout")
async def logout() -> dict:
    """Logout the current user.

    Note: Since we use JWT tokens, logout is handled client-side
    by discarding the token. This endpoint is provided for API completeness.
    """
    return {"message": "Successfully logged out"}
