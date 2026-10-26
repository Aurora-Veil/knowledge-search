"""GET /api/v1/stats/reports, GET /api/v1/stats/search"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from elasticsearch import ApiError, TransportError
from fastapi import APIRouter, HTTPException, Query

from ..auth.deps import ActiveUser
from ..search import stats_reports
from ..searchlog import stats as searchlog_stats

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

_ES_UNAVAILABLE = (ApiError, TransportError)


@router.get("/reports")
def api_report_stats(user: ActiveUser) -> dict[str, Any]:
    try:
        return stats_reports.overview()
    except _ES_UNAVAILABLE as exc:
        log.warning("report stats unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="report stats unavailable") from exc


@router.get("/search")
def api_search_stats(
    user: ActiveUser,
    start: date | None = Query(None, description="起始日，含"),
    end: date | None = Query(None, description="结束日，含"),
    days: int = Query(14, ge=1, le=366, description="没传 start/end 时的回看天数"),
    queries: list[str] | None = Query(None, description="只看这些检索词，最多 20 个"),
    scope: Literal["all", "me"] = Query("all"),
    kind: Literal["oirf", "report"] | None = Query(None, description="None = all"),
    granularity: Literal["day", "week", "month"] = Query("day"),
    limit: int = Query(5, ge=1, le=20, description="Top 检索词条数"),
) -> dict[str, Any]:
    try:
        return searchlog_stats.overview(
            user.id,
            days=days,
            start=start,
            end=end,
            queries=queries,
            scope=scope,
            kind=kind,
            granularity=granularity,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except searchlog_stats.UNAVAILABLE as exc:
        log.warning("search stats unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="search stats unavailable") from exc
