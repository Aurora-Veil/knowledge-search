"""GET /api/v1/stats/report-library, GET /api/v1/stats/search-activity"""
from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import Any, Literal

from elasticsearch import ApiError, TransportError
from fastapi import APIRouter, HTTPException, Query

from ..auth.deps import ActiveUser
from ..cache import redis as cache
from ..search import stats_reports
from ..searchlog import stats as searchlog_stats

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

_ES_UNAVAILABLE = (ApiError, TransportError)

_REPORTS_KEY = "stats:reports"
_REPORTS_TTL = 600

# 已结束的日期不会再变（汇总表凌晨才更新），可以缓存一天；
_SEARCH_TTL_CLOSED = 86400
_SEARCH_TTL_OPEN = 60


def _search_key(start: date, end: date, queries: list[str],
                kind: str | None, granularity: str, limit: int) -> str:
    raw = "|".join([
        start.isoformat(), end.isoformat(), kind or "", granularity,
        str(limit), ",".join(sorted(queries)),
    ])
    return "stats:search:" + hashlib.md5(raw.encode("utf-8")).hexdigest()


@router.get("/report-library")
def api_report_stats(user: ActiveUser) -> dict[str, Any]:
    cached = cache.load_json(_REPORTS_KEY)
    if cached is not None:
        return cached

    try:
        body = stats_reports.overview()
    except _ES_UNAVAILABLE as exc:
        log.warning("report stats unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="report stats unavailable") from exc

    cache.store_json(_REPORTS_KEY, body, _REPORTS_TTL)
    return body


@router.get("/search-activity")
def api_search_stats(
    user: ActiveUser,
    start: date | None = Query(None, description="起始日，含"),
    end: date | None = Query(None, description="结束日，含"),
    days: int = Query(14, ge=1, le=366, description="没传 start/end 时的回看天数"),
    queries: list[str] | None = Query(None, description="只看这些检索词，最多 20 个"),
    kind: Literal["oirf", "report"] | None = Query(None, description="None = all"),
    granularity: Literal["day", "week", "month"] = Query("day"),
    limit: int = Query(5, ge=1, le=20, description="Top 检索词条数"),
) -> dict[str, Any]:
    """只读汇总表 search_daily，不读 search_log；今天的数据不在范围内。"""
    try:
        now = searchlog_stats.today()
        start_at, end_at = searchlog_stats.resolve_range(days, start, end, now=now)
        picked = searchlog_stats.normalize_queries(queries)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    key = _search_key(start_at, end_at, picked, kind, granularity, limit)
    cached = cache.load_json(key)
    if cached is not None:
        return cached

    try:
        body = searchlog_stats.overview(
            start=start_at,
            end=end_at,
            queries=picked,
            kind=kind,
            granularity=granularity,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except searchlog_stats.UNAVAILABLE as exc:
        log.warning("search stats unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="search stats unavailable") from exc

    ttl = _SEARCH_TTL_CLOSED if end_at < now else _SEARCH_TTL_OPEN
    cache.store_json(key, body, ttl)
    return body
