"""Password hashing via pwdlib's established Argon2 implementation."""

from __future__ import annotations

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()

# A pre-computed hash used to equalize timing when the login identifier
# is unknown, so attackers cannot enumerate logins via response timing.
_DUMMY_HASH = _hasher.hash("timing-equalization-dummy-password")


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2 (never store plaintext)."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored Argon2 hash."""
    return _hasher.verify(password, password_hash)


def dummy_verify(password: str) -> None:
    """Burn comparable verification time for unknown login identifiers."""
    _hasher.verify(password, _DUMMY_HASH)
