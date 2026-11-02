"""GET /api/v1/stats/summary：检索端首页那一行报告库数字。

全站统计在 /api/v1/admin/stats/*，只有管理员能调。
"""
from __future__ import annotations

import logging
from typing import Any

from elasticsearch import ApiError, TransportError
from fastapi import APIRouter, HTTPException

from ..auth.deps import ActiveUser
from ..cache import redis as cache
from ..search import stats_reports

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

_ES_UNAVAILABLE = (ApiError, TransportError)

_SUMMARY_KEY = "stats:summary:v1"
_SUMMARY_TTL = 600


@router.get("/summary")
def api_summary(user: ActiveUser) -> dict[str, Any]:
    """报告总量、行业数、发布年份范围。"""
    cached = cache.load_json(_SUMMARY_KEY)
    if cached is not None:
        return cached

    try:
        body = stats_reports.summary()
    except _ES_UNAVAILABLE as exc:
        log.warning("report summary unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="report stats unavailable") from exc

    cache.store_json(_SUMMARY_KEY, body, _SUMMARY_TTL)
    return body
