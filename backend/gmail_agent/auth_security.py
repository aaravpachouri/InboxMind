"""Password and one-time-token primitives for InboxMind email authentication.

This module deliberately contains no database, mail-provider, or HTTP side effects.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 600_000
_SALT_BYTES = 16
_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    """Return a versioned PBKDF2-SHA256 hash suitable for storage."""
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValueError("Password must contain between 12 and 1024 characters.")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return "$".join(
        (
            _PASSWORD_SCHEME,
            str(_PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a stored password hash; malformed or unknown formats fail closed."""
    try:
        scheme, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        iterations = int(iterations_text)
        if scheme != _PASSWORD_SCHEME or not 100_000 <= iterations <= 2_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        if len(salt) != _SALT_BYTES or len(expected) != hashlib.sha256().digest_size:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return False


def create_one_time_token() -> tuple[str, bytes]:
    """Return a high-entropy URL-safe token and its SHA-256 digest for storage."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    return token, hashlib.sha256(token.encode("ascii")).digest()


def hash_one_time_token(token: str) -> bytes:
    """Hash a presented one-time token for constant-shape database lookup."""
    if not isinstance(token, str) or not 20 <= len(token) <= 256:
        raise ValueError("Invalid one-time token.")
    return hashlib.sha256(token.encode("ascii")).digest()
