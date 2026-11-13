"""Password hashing (Argon2) and session tokens (HS256 JWT in an httpOnly cookie)."""

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from backend.app.config import Settings

log = logging.getLogger("irminsul.security")

_ph = PasswordHasher()
_ALGORITHM = "HS256"


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_ph.hash, password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def _dummy_hash() -> str:
    return _ph.hash(secrets.token_urlsafe(16))


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-ish time: unknown users still pay for one Argon2 verify."""
    ok = await asyncio.to_thread(_verify, password_hash or _dummy_hash(), password)
    return ok and password_hash is not None


@lru_cache
def _ephemeral_secret() -> str:
    log.warning("JWT_SECRET not set: using an ephemeral secret (sessions reset on restart)")
    return secrets.token_urlsafe(48)


def _secret(settings: Settings) -> str:
    if settings.jwt_secret is not None:
        return settings.jwt_secret.get_secret_value()
    if settings.environment == "production":
        raise RuntimeError("JWT_SECRET must be set in production")
    return _ephemeral_secret()


def create_session_token(user_id: str, role: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.session_ttl_hours),
    }
    return jwt.encode(payload, _secret(settings), algorithm=_ALGORITHM)


def decode_session_token(token: str, settings: Settings) -> dict[str, Any] | None:
    try:
        return jwt.decode(
            token, _secret(settings), algorithms=[_ALGORITHM], options={"require": ["sub", "exp"]}
        )
    except jwt.PyJWTError:
        return None
