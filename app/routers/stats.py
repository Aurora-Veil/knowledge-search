"""GET /api/v1/stats/reports, GET /api/v1/stats/search"""
from __future__ import annotations

import logging
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
    days: int = Query(14, ge=1, le=90),
    scope: Literal["all", "me"] = Query("all"),
    kind: Literal["oirf", "report"] | None = Query(None, description="None = all"),
) -> dict[str, Any]:
    try:
        return searchlog_stats.overview(user.id, days, scope, kind)
    except searchlog_stats.UNAVAILABLE as exc:
        log.warning("search stats unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="search stats unavailable") from exc
