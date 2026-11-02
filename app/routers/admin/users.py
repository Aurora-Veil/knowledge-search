"""用户管理：列表、详情、改角色与启停。"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from ...auth import admin as users_store
from ...auth.deps import AdminUser

router = APIRouter(prefix="/users")

Role = Literal["user", "admin"]


class UserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


@router.get("")
def api_list_users(
    q: str | None = Query(None, max_length=64, description="用户名模糊匹配"),
    role: Role | None = Query(None, description="None = 全部"),
    active: bool | None = Query(None, description="None = 全部"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    try:
        return users_store.list_users(
            q=q, role=role, active=active, limit=limit, offset=offset
        )
    except users_store.UNAVAILABLE as exc:
        raise HTTPException(status_code=503, detail="user database unavailable") from exc


@router.get("/{user_id}")
def api_get_user(user_id: int = Path(..., ge=1)) -> dict[str, Any]:
    try:
        user = users_store.get_user(user_id)
    except users_store.UNAVAILABLE as exc:
        raise HTTPException(status_code=503, detail="user database unavailable") from exc

    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@router.patch("/{user_id}")
def api_update_user(
    payload: UserPatch,
    admin: AdminUser,
    user_id: int = Path(..., ge=1),
) -> dict[str, Any]:
    """改角色、停用或启用。不能作用于自己，也不能撤掉最后一个管理员。"""
    if payload.role is None and payload.is_active is None:
        raise HTTPException(status_code=422, detail="role or is_active is required")

    try:
        return users_store.update_user(
            actor_id=admin.id,
            user_id=user_id,
            role=payload.role,
            active=payload.is_active,
        )
    except users_store.UserNotFound as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    except users_store.Rejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except users_store.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except users_store.UNAVAILABLE as exc:
        raise HTTPException(status_code=503, detail="user database unavailable") from exc
