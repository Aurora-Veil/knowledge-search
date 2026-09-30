"""JWT access tokens: issue and verify."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from ..config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, jwt_secret


def create_access_token(subject: str) -> str:
    """Sign a token asserting "the bearer is user <subject>"."""
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire_at}
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the subject, or None if the token is missing/expired/forged."""
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None