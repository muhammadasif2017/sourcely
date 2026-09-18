"""Password hashing, random tokens and the common-password check."""

import hashlib
import secrets
from functools import cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi's defaults follow RFC 9106's recommended Argon2id parameters.
_hasher = PasswordHasher()

# Checked when an email has no account, so a failed sign-in takes about as long either way
# and response time doesn't reveal which emails are registered.
DUMMY_PASSWORD_HASH = _hasher.hash("not-a-real-password-used-for-timing-only")

_COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")


def hash_password(password: str) -> str:
    """An Argon2id hash with a random salt, in the standard `$argon2id$...` format."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True when `password` matches. Never raises, even for a malformed hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    """32 random bytes, URL-safe: for sessions, CSRF, and email and invite links."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """SHA-256 of a token, which is what the database stores.

    A fast hash is enough here, unlike for passwords: the token is 32 random bytes, so it
    can't be guessed, and a stolen database row can't be turned back into a usable token.
    """
    return hashlib.sha256(token.encode()).digest()


@cache
def _common_passwords() -> frozenset[str]:
    lines = _COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line for line in lines if line and not line.startswith("#"))


def is_common_password(password: str) -> bool:
    """True if the password is on the bundled common-passwords list, ignoring case."""
    return password.lower() in _common_passwords()
