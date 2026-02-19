"""Authentication service for user management and JWT tokens."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, OAuth2PasswordBearer
from jose import JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from winebox.config import settings
from winebox.models.user import User

# Password hashing using pwdlib (compatible with fastapi-users)
password_hash = PasswordHash((BcryptHasher(),))

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

# HTTP Basic auth scheme (for login form)
http_basic = HTTPBasic(auto_error=False)

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return password_hash.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt


async def get_user_by_username(username: str) -> User | None:
    """Get a user by username."""
    return await User.find_one(User.username == username)


async def get_user_by_email(email: str) -> User | None:
    """Get a user by email."""
    return await User.find_one(User.email == email)


async def get_user_by_username_or_email(identifier: str) -> User | None:
    """Get a user by username or email.

    This supports login with either username or email address.
    """
    # First try username
    user = await get_user_by_username(identifier)
    if user:
        return user

    # Then try email
    return await get_user_by_email(identifier)


async def authenticate_user(username: str, password: str) -> User | None:
    """Authenticate a user with username/email and password.

    Args:
        username: Username or email address.
        password: Plain text password.

    Returns:
        User if authentication successful, None otherwise.
    """
    user = await get_user_by_username_or_email(username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User | None:
    """Get the current user from the JWT token.

    Supports tokens with 'sub' containing either username or user_id (ObjectId string).
    """
    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        subject: str | None = payload.get("sub")
        if subject is None:
            return None
    except JWTError:
        return None

    # Try to find user - subject could be username, email, or user_id
    user = await get_user_by_username_or_email(subject)

    # If not found by username/email, try as user_id (ObjectId)
    if user is None:
        try:
            user_id = PydanticObjectId(subject)
            user = await User.get(user_id)
        except Exception:
            pass  # Not a valid ObjectId

    if user is None or not user.is_active:
        return None

    return user


async def require_auth(
    user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    """Require authentication - raises 401 if not authenticated."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(
    user: Annotated[User, Depends(require_auth)],
) -> User:
    """Require admin privileges."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


# Type aliases for dependency injection
CurrentUser = Annotated[User | None, Depends(get_current_user)]
RequireAuth = Annotated[User, Depends(require_auth)]
RequireAdmin = Annotated[User, Depends(require_admin)]
