"""Password hashing (bcrypt) and JWT (HS256) helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

JWT_ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12
MAX_PASSWORD_BYTES = 72  # bcrypt only uses the first 72 bytes

# A valid hash of a random string, used to equalise timing when an email is unknown.
_DUMMY_HASH = bcrypt.hashpw(b"eventlens-timing-equaliser", bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError("Password must be at most 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        bcrypt.checkpw(b"x", _DUMMY_HASH.encode())
        return False
    try:
        return bcrypt.checkpw(raw, (password_hash or _DUMMY_HASH).encode()) and password_hash is not None
    except ValueError:
        return False


def create_access_token(admin_id: int, email: str) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=s.JWT_EXPIRE_MINUTES)
    payload = {"sub": str(admin_id), "email": email, "iat": now, "exp": exp, "typ": "access"}
    return jwt.encode(payload, s.JWT_SECRET, algorithm=JWT_ALGORITHM), s.JWT_EXPIRE_MINUTES * 60


def decode_access_token(token: str) -> dict:
    """Decode and validate a token; raises jwt.PyJWTError on any problem."""
    payload = jwt.decode(
        token,
        get_settings().JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "sub", "iat"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload
