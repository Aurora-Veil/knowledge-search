"""检索日志：明细与汇总，只有管理员能调。"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from ...searchlog import admin as logs

router = APIRouter(prefix="/search-logs")


@router.get("")
def api_search_logs(
    start: date | None = Query(None, description="起始日，含"),
    end: date | None = Query(None, description="结束日，含"),
    days: int = Query(logs.DEFAULT_DAYS, ge=1, le=logs.MAX_SPAN_DAYS,
                      description="没传 start/end 时的回看天数"),
    kind: Literal["oirf", "report"] | None = Query(None, description="None = 全部"),
    outcome: Literal["ok", "error"] | None = Query(None, description="None = 全部"),
    user_id: int | None = Query(None, ge=1, description="只看某个账号"),
    cursor: str | None = Query(None, description="上一页返回的 next"),
    limit: int = Query(logs.DEFAULT_LIMIT, ge=1, le=logs.MAX_LIMIT),
) -> dict[str, Any]:
    try:
        return logs.list_logs(
            days=days, start=start, end=end, kind=kind, outcome=outcome,
            user_id=user_id, cursor=cursor, limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except logs.UNAVAILABLE as exc:
        raise HTTPException(status_code=503, detail="search logs unavailable") from exc


@router.get("/summary")
def api_search_log_summary(
    start: date | None = Query(None, description="起始日，含"),
    end: date | None = Query(None, description="结束日，含"),
    days: int = Query(logs.DEFAULT_DAYS, ge=1, le=logs.MAX_SPAN_DAYS,
                      description="没传 start/end 时的回看天数"),
    kind: Literal["oirf", "report"] | None = Query(None, description="None = 全部"),
    user_id: int | None = Query(None, ge=1,
                                description="只看某个账号，延迟分位和失败原因不适用"),
) -> dict[str, Any]:
    """只读按天的小表，不读 search_log；今天的数据还没汇总。"""
    try:
        return logs.summary(days=days, start=start, end=end, kind=kind, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except logs.UNAVAILABLE as exc:
        raise HTTPException(status_code=503, detail="search logs unavailable") from exc
