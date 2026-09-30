"""Auth routes: POST /register, POST /token, GET /me."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, field_validator

from ..auth import errors
from ..auth.deps import ActiveUser
from ..auth.password import hash_password, verify_password
from ..auth.store import (
    InvalidPassword,
    InvalidUsername,
    UsernameTaken,
    User,
    UserStoreUnavailable,
    user_store,
    validate_password,
    validate_username,
)
from ..auth.token import create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


_DUMMY_HASH = hash_password("timing-equalisation-dummy-password")


class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        try:
            return validate_username(value)
        except InvalidUsername as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        try:
            return validate_password(value)
        except InvalidPassword as exc:
            raise ValueError(str(exc)) from exc


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest) -> User:
    """Create an account."""
    try:
        return user_store.create(payload.username, hash_password(payload.password))
    except UsernameTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except UserStoreUnavailable as exc:
        raise errors.unavailable() from exc


@router.post("/token", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    """OAuth2 password flow: form-encoded username=...&password=..."""
    try:
        user = user_store.find_by_username(form.username)
    except UserStoreUnavailable as exc:
        raise errors.unavailable() from exc

    stored = user.password_hash if user is not None else _DUMMY_HASH
    password_ok = verify_password(form.password, stored)

    if user is None or not password_ok:
        raise errors.unauthorized("Incorrect username or password")

    if not user.is_active:
        raise errors.inactive()

    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserResponse)
def read_me(user: ActiveUser) -> User:
    """The caller's own account, resolved from the bearer token."""
    return user
