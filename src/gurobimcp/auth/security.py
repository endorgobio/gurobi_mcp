"""Security primitives (T014): password hashing, secret encryption, JWTs.

All license-free and unit-testable. FR-002/003: passwords are bcrypt-hashed;
FR-004: Gurobi secrets are Fernet-encrypted at rest; FR-006: auth tokens are
time-limited JWTs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

# bcrypt operates on at most 72 bytes; truncate consistently in hash and verify.
_BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """Raised when an auth token is missing, malformed, expired, or invalid."""


# --- Passwords (bcrypt) ---


def _pw_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


# --- Gurobi secret encryption (Fernet) ---


def encrypt_secret(plaintext: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str, key: str) -> str:
    try:
        return Fernet(key.encode()).decrypt(token.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - defensive
        raise ValueError("Could not decrypt secret with the provided key") from exc


# --- Auth tokens (JWT) ---


def create_access_token(subject: str, secret: str, ttl: int, algorithm: str = "HS256") -> str:
    now = datetime.now(UTC)
    payload = {"sub": subject, "iat": now, "exp": now + timedelta(seconds=ttl)}
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, secret: str, algorithm: str = "HS256") -> str:
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise TokenError("Token missing subject")
    return subject
