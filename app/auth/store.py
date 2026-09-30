"""User storage backed by PostgreSQL."""
from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

import psycopg

from ..db import get_pg

# username: 3..32 chars, letters / digits / underscore / hyphen
USERNAME_RE = re.compile(r"[A-Za-z0-9_-]{3,32}")

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class UserStoreError(Exception):
    """Base class for user storage failures."""


class UsernameTaken(UserStoreError):
    """Username is already taken"""


class InvalidUsername(UserStoreError):
    """Username is invalid"""


class InvalidPassword(UserStoreError):
    """Password is invalid"""


class UserStoreUnavailable(UserStoreError):
    """The database is unreachable"""


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    is_active: bool = True
    created_at: datetime | None = None


def validate_username(username: str) -> str:
    cleaned = (username or "").strip()
    if not USERNAME_RE.fullmatch(cleaned):
        raise InvalidUsername(
            "username must be 3-32 characters of letters, digits, _ or -"
        )
    return cleaned


def validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidPassword(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvalidPassword(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    return password


@contextmanager
def _connection() -> Generator[psycopg.Connection, None, None]:
    """Borrow a pooled connection, turning outages into UserStoreUnavailable."""
    try:
        with get_pg().connection() as conn:
            yield conn
    except psycopg.OperationalError as exc:
        raise UserStoreUnavailable("database unavailable") from exc


_USER_COLUMNS = "id, username, password_hash, is_active, created_at"


class UserStore:
    """PostgreSQL-backed user table."""
    def create(self, username: str, password_hash: str) -> User:
        cleaned = validate_username(username)

        with _connection() as conn:
            try:
                row = conn.execute(
                    f"""
                    INSERT INTO users (username, password_hash)
                    VALUES (%s, %s)
                    RETURNING {_USER_COLUMNS}
                    """,
                    (cleaned, password_hash),
                ).fetchone()
            except psycopg.errors.UniqueViolation as exc:
                raise UsernameTaken(f"username already taken: {cleaned}") from exc
        return _row_to_user(row)

    def get(self, user_id: int) -> User | None:
        with _connection() as conn:
            row = conn.execute(
                f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s",
                (user_id,),
            ).fetchone()
        return _row_to_user(row) if row else None

    def find_by_username(self, username: str) -> User | None:
        key = (username or "").strip().lower()
        if not key:
            return None
        with _connection() as conn:
            row = conn.execute(
                f"""
                SELECT {_USER_COLUMNS} FROM users
                WHERE lower(btrim(username)) = %s
                """,
                (key,),
            ).fetchone()
        return _row_to_user(row) if row else None

    def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        with _connection() as conn:
            cur = conn.execute(
                """
                UPDATE users
                   SET password_hash = %s, updated_at = now()
                 WHERE id = %s
                """,
                (password_hash, user_id),
            )
            return cur.rowcount > 0

    def set_active(self, user_id: int, active: bool) -> bool:
        with _connection() as conn:
            cur = conn.execute(
                "UPDATE users SET is_active = %s, updated_at = now() WHERE id = %s",
                (active, user_id),
            )
            return cur.rowcount > 0

    def count(self) -> int:
        with _connection() as conn:
            return conn.execute("SELECT count(*) FROM users").fetchone()[0]


def _row_to_user(row: tuple) -> User:
    return User(
        id=row[0],
        username=row[1],
        password_hash=row[2],
        is_active=row[3],
        created_at=row[4],
    )


user_store = UserStore()
