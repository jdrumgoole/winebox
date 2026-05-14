"""Auth integration — embeds the regstack library.

User registration, login, password reset, email verification, and JWT
issuance are owned by `regstack`. Construction of the embedded instance
lives in :mod:`winebox.auth.regstack_setup`; FastAPI dependency
adapters live in :mod:`winebox.services.auth`.

`MIN_PASSWORD_LENGTH` is kept here because admin endpoints and the CLI
import it for length-validation on operator-created users.
"""

from winebox.auth.schemas import MIN_PASSWORD_LENGTH

__all__ = ["MIN_PASSWORD_LENGTH"]
