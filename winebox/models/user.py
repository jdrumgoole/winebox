"""User document model for authentication with fastapi-users integration."""

import logging
from datetime import datetime
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field

logger = logging.getLogger(__name__)


class User(Document):
    """User document model for authentication.

    This model is compatible with fastapi-users BeanieUserDatabase.

    Fields:
    - id: ObjectId primary key (from Document)
    - email: unique email (required by fastapi-users)
    - hashed_password: password hash
    - is_active: account active status
    - is_verified: email verification status
    - is_superuser: admin/superuser status

    Custom fields added for WineBox:
    - username: unique username for display
    - full_name: optional full name
    - anthropic_api_key: user's API key for Claude Vision (encrypted at rest)
    - created_at, updated_at: timestamps
    - last_login: last login timestamp

    Note: API keys are stored encrypted at rest. Use the helper methods
    `get_decrypted_api_key()` and `set_encrypted_api_key()` for access.
    """

    # Required fields for fastapi-users
    email: Indexed(str, unique=True)
    hashed_password: str
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False

    # Custom fields for WineBox
    username: Indexed(str, unique=True)
    full_name: Optional[str] = None
    # API key is stored encrypted at rest
    anthropic_api_key: Optional[str] = None

    def get_decrypted_api_key(self) -> Optional[str]:
        """Get the decrypted API key.

        Returns:
            Decrypted API key or None if not set.
        """
        if not self.anthropic_api_key:
            return None

        try:
            from winebox.services.crypto import decrypt_value, is_encrypted

            if is_encrypted(self.anthropic_api_key):
                return decrypt_value(self.anthropic_api_key)
            # Handle legacy unencrypted values
            return self.anthropic_api_key
        except Exception as e:
            logger.error(f"Failed to decrypt API key for user {self.id}: {e}")
            return None

    def set_encrypted_api_key(self, plaintext_key: Optional[str]) -> None:
        """Set the API key, encrypting it for storage.

        Args:
            plaintext_key: Plaintext API key to encrypt and store.
        """
        if not plaintext_key:
            self.anthropic_api_key = None
            return

        try:
            from winebox.services.crypto import encrypt_value, is_encrypted

            # Don't double-encrypt
            if is_encrypted(plaintext_key):
                self.anthropic_api_key = plaintext_key
            else:
                self.anthropic_api_key = encrypt_value(plaintext_key)
        except Exception as e:
            logger.error(f"Failed to encrypt API key: {e}")
            raise ValueError("Failed to encrypt API key") from e

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None

    class Settings:
        name = "users"
        use_state_management = True
        email_collation = None  # Use default case-insensitive collation

    # Alias is_superuser as is_admin for backward compatibility
    @property
    def is_admin(self) -> bool:
        """Alias for is_superuser for backward compatibility."""
        return self.is_superuser

    @is_admin.setter
    def is_admin(self, value: bool) -> None:
        """Set is_superuser via is_admin alias."""
        self.is_superuser = value

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, email={self.email}, is_active={self.is_active})>"
