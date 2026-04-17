"""Authentication service for user management and JWT tokens."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, OAuth2PasswordBearer
import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from winebox.config import settings
from winebox.models.user import User

# Security event logger
security_logger = logging.getLogger("winebox.security")

# Password hashing using pwdlib with Argon2 (matches fastapi-users default)
password_hash = PasswordHash((Argon2Hasher(),))

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

# HTTP Basic auth scheme (for login form)
http_basic = HTTPBasic(auto_error=False)

# JWT settings - single source of truth for token lifetime
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120  # 2 hours (reduced for security)
TOKEN_LIFETIME_SECONDS = ACCESS_TOKEN_EXPIRE_MINUTES * 60  # For consistency with backend.py


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return password_hash.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return password_hash.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token with jti (per-token revocation) and iat
    (issued-at, used by the bulk per-user invalidation cutoff)."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())
    to_encode.update({"exp": expire, "iat": now, "jti": jti})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt


async def get_user_by_email(email: str) -> User | None:
    """Get a user by email (normalised to lowercase)."""
    return await User.find_one({"email": email.lower()})


async def authenticate_user(
    email: str,
    password: str,
    ip_address: str | None = None,
) -> User | None:
    """Authenticate a user with email and password.

    Includes account lockout protection after too many failed attempts.

    Args:
        email: User's email address.
        password: Plain text password.
        ip_address: Client IP address for logging.

    Returns:
        User if authentication successful, None otherwise.

    Raises:
        HTTPException: If account is locked out.
    """
    from winebox.models.login_attempt import LoginAttempt

    # Check for account lockout
    if await LoginAttempt.is_locked_out(email):
        remaining = await LoginAttempt.get_lockout_remaining_seconds(email)
        security_logger.warning(
            "Login attempt blocked - account locked: email=%s, ip=%s, remaining_seconds=%d",
            email,
            ip_address or "unknown",
            remaining,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked. Try again in {remaining // 60 + 1} minutes.",
            headers={"Retry-After": str(remaining)},
        )

    user = await get_user_by_email(email)

    # Always verify password to prevent timing-based user enumeration
    # If user doesn't exist, verify against a dummy hash (same time cost)
    if user:
        password_valid = verify_password(password, user.hashed_password)
    else:
        # Dummy hash to ensure constant-time comparison even for non-existent users
        # This is a valid Argon2 hash that will never match any input
        dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$Md2wFrOYTTHUZQ+9BMQ30Q$0++2tWFRb3NhF1aF3Xkos3RtheYbLA7S0gH4qC9jf50"
        verify_password(password, dummy_hash)
        password_valid = False

    if not user:
        # Record failed attempt - user not found
        await LoginAttempt.record_attempt(email, failed=True, ip_address=ip_address)
        security_logger.warning(
            "Failed login - user not found: email=%s, ip=%s",
            email,
            ip_address or "unknown",
        )
        return None

    if not password_valid:
        # Record failed attempt - wrong password
        await LoginAttempt.record_attempt(email, failed=True, ip_address=ip_address)
        security_logger.warning(
            "Failed login - invalid password: user_id=%s, ip=%s",
            str(user.id),
            ip_address or "unknown",
        )
        return None

    if not user.is_active:
        # Record failed attempt - inactive account
        await LoginAttempt.record_attempt(email, failed=True, ip_address=ip_address)
        security_logger.warning(
            "Failed login - inactive account: user_id=%s, ip=%s",
            str(user.id),
            ip_address or "unknown",
        )
        return None

    # Successful login - clear failed attempts
    await LoginAttempt.clear_attempts(email)
    security_logger.info(
        "Successful login: user_id=%s, ip=%s",
        str(user.id),
        ip_address or "unknown",
    )

    return user


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User | None:
    """Get the current user from the JWT token.

    Supports tokens with 'sub' containing email or user_id (ObjectId string).
    Also checks if the token has been revoked.
    """
    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        subject: str | None = payload.get("sub")
        jti: str | None = payload.get("jti")
        iat_raw = payload.get("iat")
        if subject is None:
            return None
    except jwt.PyJWTError:
        return None

    # Check if token is revoked
    if jti:
        from winebox.models.token_blacklist import RevokedToken

        if await RevokedToken.is_revoked(jti):
            return None

    # Try to find user - subject could be email or user_id
    user = await get_user_by_email(subject)

    # If not found by email, try as user_id (ObjectId)
    if user is None:
        try:
            user_id = ObjectId(subject)
            user = await User.get(user_id)
        except Exception:
            pass  # Not a valid ObjectId

    if user is None or not user.is_active:
        return None

    # Bulk per-user invalidation: any token issued before the cutoff is dead.
    # Tokens minted before the iat claim was added (iat_raw is None) are
    # treated as predating any cutoff, i.e. invalidated by any cutoff.
    if user.tokens_invalidated_after is not None:
        if iat_raw is None:
            return None
        iat = datetime.fromtimestamp(iat_raw, tz=timezone.utc)
        cutoff = user.tokens_invalidated_after
        # MongoDB returns BSON Dates as offset-naive UTC; normalise.
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        if iat < cutoff:
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


async def revoke_token(token: str, user_id: str | None = None, reason: str = "logout") -> bool:
    """Revoke a JWT token by adding it to the blacklist.

    Args:
        token: The JWT token to revoke.
        user_id: Optional user ID for audit purposes.
        reason: Reason for revocation.

    Returns:
        True if token was successfully revoked, False otherwise.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        jti: str | None = payload.get("jti")
        exp: int | None = payload.get("exp")

        if not jti or not exp:
            return False

        from winebox.models.token_blacklist import RevokedToken

        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        await RevokedToken.revoke_token(
            jti=jti,
            expires_at=expires_at,
            user_id=user_id,
            reason=reason,
        )

        security_logger.info(
            "Token revoked: user_id=%s, reason=%s, jti=%s",
            user_id or "unknown",
            reason,
            jti,
        )
        return True
    except jwt.PyJWTError:
        security_logger.warning("Token revocation failed - invalid JWT: user_id=%s", user_id)
        return False
    except Exception as e:
        security_logger.error("Token revocation failed - error: user_id=%s, error=%s", user_id, str(e))
        return False


async def revoke_all_user_tokens(user: User, reason: str = "credential_rotation") -> None:
    """Invalidate every existing JWT for this user in one shot.

    Sets `tokens_invalidated_after` to the current UTC time. `get_current_user`
    rejects any token whose `iat` claim is earlier than this cutoff. We add
    one second of slop so that newly-minted tokens issued in the same wall
    clock instant (e.g. a fresh login immediately after a password change)
    are not accidentally invalidated.
    """
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
    user.tokens_invalidated_after = cutoff
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    security_logger.info(
        "All tokens invalidated: user_id=%s, reason=%s, cutoff=%s",
        str(user.id),
        reason,
        cutoff.isoformat(),
    )


# Type aliases for dependency injection
CurrentUser = Annotated[User | None, Depends(get_current_user)]
RequireAuth = Annotated[User, Depends(require_auth)]
RequireAdmin = Annotated[User, Depends(require_admin)]
