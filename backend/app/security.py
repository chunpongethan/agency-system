"""
Password hashing and JWT helpers.

Secret and token lifetime come from the environment so nothing sensitive lives
in code. Passwords are bcrypt-hashed via passlib; tokens are HS256 JWTs.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me-0123456789-abcdef-0123456789")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "30"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT. Raises jwt.PyJWTError on any problem."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def _fingerprint(password_hash: str | None) -> str:
    """A short, non-reversible marker of the current password hash. Embedding it
    in a reset token makes the token single-use: once the password changes the
    hash (and thus the fingerprint) changes, so an old reset link stops working."""
    return (password_hash or "")[-10:]


def create_reset_token(subject: str, password_hash: str | None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "purpose": "pwreset",
        "fp": _fingerprint(password_hash),
        "iat": now,
        "exp": now + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_reset_token(token: str, password_hash: str | None) -> bool:
    """True if `token` is a valid, unexpired reset token for this password hash."""
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return False
    return (payload.get("purpose") == "pwreset"
            and payload.get("fp") == _fingerprint(password_hash))
