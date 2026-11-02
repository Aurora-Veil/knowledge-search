"""HTTP translations for the auth domain."""
from __future__ import annotations

from fastapi import HTTPException, status


def unauthorized(detail: str = "Could not validate credentials") -> HTTPException:
    """401 plus the WWW-Authenticate challenge RFC 6750 requires."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def inactive() -> HTTPException:
    """403: the caller is authenticated, but not allowed."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Inactive user",
    )


def forbidden(detail: str = "Admin privilege required") -> HTTPException:
    """403: the caller is an active user, but not an admin."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def unavailable() -> HTTPException:
    """503 for a database outage."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="User database unavailable",
    )
