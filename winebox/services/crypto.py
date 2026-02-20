"""Cryptography service for encrypting sensitive data at rest.

Uses Fernet symmetric encryption with a key derived from the application secret.
"""

import base64
import hashlib
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Prefix to identify encrypted values
ENCRYPTED_PREFIX = "enc:"


def _derive_key(secret: str) -> bytes:
    """Derive a Fernet-compatible key from the application secret.

    Args:
        secret: The application secret key.

    Returns:
        A 32-byte key suitable for Fernet.
    """
    # Use SHA-256 to derive a consistent 32-byte key from any secret
    key_bytes = hashlib.sha256(secret.encode()).digest()
    # Fernet requires URL-safe base64 encoded 32-byte key
    return base64.urlsafe_b64encode(key_bytes)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Get the Fernet instance for encryption/decryption.

    Returns:
        Fernet instance configured with the derived key.
    """
    from winebox.config import settings

    key = _derive_key(settings.secret_key)
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value.

    Args:
        plaintext: The value to encrypt.

    Returns:
        Encrypted value with prefix for identification.
    """
    if not plaintext:
        return plaintext

    try:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(plaintext.encode())
        return ENCRYPTED_PREFIX + encrypted.decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise ValueError("Failed to encrypt value") from e


def decrypt_value(ciphertext: str) -> str:
    """Decrypt an encrypted string value.

    Args:
        ciphertext: The encrypted value (with or without prefix).

    Returns:
        Decrypted plaintext value.

    Raises:
        ValueError: If decryption fails.
    """
    if not ciphertext:
        return ciphertext

    # Handle both prefixed and non-prefixed values
    if ciphertext.startswith(ENCRYPTED_PREFIX):
        ciphertext = ciphertext[len(ENCRYPTED_PREFIX) :]

    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()
    except InvalidToken:
        logger.error("Decryption failed: invalid token (wrong key or corrupted data)")
        raise ValueError("Failed to decrypt value: invalid token")
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise ValueError("Failed to decrypt value") from e


def is_encrypted(value: str) -> bool:
    """Check if a value is already encrypted.

    Args:
        value: The value to check.

    Returns:
        True if the value has the encryption prefix.
    """
    return bool(value and value.startswith(ENCRYPTED_PREFIX))


def reset_fernet_cache() -> None:
    """Reset the Fernet instance cache.

    Useful for testing when the secret key changes.
    """
    _get_fernet.cache_clear()
