"""FastAPI dependencies: turn an Authorization header into a User."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from . import errors
from .store import User, UserStoreUnavailable, user_store
from .token import decode_access_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Resolve a bearer token to the user it names, or raise."""
    subject = decode_access_token(token)
    if subject is None:
        raise errors.unauthorized()

    try:
        user_id = int(subject)
    except ValueError:
        raise errors.unauthorized()

    try:
        user = user_store.get(user_id)
    except UserStoreUnavailable as exc:
        raise errors.unavailable() from exc

    if user is None:
        raise errors.unauthorized()
    return user


def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_active:
        raise errors.inactive()
    return user


# 端点签名写 `user: ActiveUser`，即"必须已登录且账号未停用"。
ActiveUser = Annotated[User, Depends(get_current_active_user)]
