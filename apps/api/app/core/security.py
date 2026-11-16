from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _encode(payload: dict[str, Any], expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    body = {
        **payload,
        "iss": "sarap",
        "iat": now,
        "nbf": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(body, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(claims: dict[str, Any]) -> str:
    return _encode({"typ": "access", **claims}, timedelta(minutes=settings.access_token_minutes))


def create_refresh_token(claims: dict[str, Any]) -> str:
    return _encode({"typ": "refresh", **claims}, timedelta(days=settings.refresh_token_days))


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM], issuer="sarap")
