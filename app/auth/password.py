from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

password_hash = PasswordHash.recommended()

def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored: str) -> bool:
    try:
        return password_hash.verify(password, stored)
    except (UnknownHashError, TypeError):
        return False
