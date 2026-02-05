"""Authentication endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from winebox.database import get_db
from winebox.models.user import User
from winebox.services.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_user,
    create_access_token,
    get_current_user,
    require_auth,
    CurrentUser,
    RequireAuth,
)

router = APIRouter()


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
    is_active: bool
    is_admin: bool
    created_at: datetime
    last_login: datetime | None

    model_config = {"from_attributes": True}


@router.post("/token", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Login with username and password to get an access token."""
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
    return UserResponse.model_validate(current_user)


@router.post("/logout")
async def logout() -> dict:
    """Logout the current user.

    Note: Since we use JWT tokens, logout is handled client-side
    by discarding the token. This endpoint is provided for API completeness.
    """
    return {"message": "Successfully logged out"}
