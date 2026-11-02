"""管理员操作记录：谁在什么时候改了哪个账号。"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from ...auth import admin as admin_store

router = APIRouter(prefix="/actions")

Action = Literal["user_update", "password_reset"]


@router.get("")
def api_list_actions(
    action: Action | None = Query(None, description="None = 全部"),
    actor_id: int | None = Query(None, ge=1),
    target_id: int | None = Query(None, ge=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """倒序，新的在前。账号被删过的，对应用户名为 null。"""
    try:
        return admin_store.list_actions(
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            limit=limit,
            offset=offset,
        )
    except admin_store.UNAVAILABLE as exc:
        raise HTTPException(status_code=503, detail="user database unavailable") from exc
