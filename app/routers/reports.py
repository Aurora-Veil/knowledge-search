""" POST /api/v1/reports/search  GET /api/v1/reports/{report_id} """
from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth.deps import ActiveUser
from ..history import store as history
from ..search.query_reports import WindowTooDeep
from ..search.service_reports import get as get_report
from ..search.service_reports import search as search_service
from ..searchlog import store as search_log

router = APIRouter(prefix="/api/v1", tags=["reports"])


class ReportSearchRequest(BaseModel):
    q: str = Field(..., min_length=1)

    # exact match
    report_id: Optional[List[str]] = None
    layout: Optional[str] = None
    industry: Optional[List[str]] = None
    publish_date_from: Optional[date] = None
    publish_date_to: Optional[date] = None

    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    highlight: bool = True

    mode: Literal["or", "and", "phrase"] = "or"
    time_weight: float = Field(0.0, ge=0.0, le=1.0, description="时间衰减权重")


# @router.post("/reports/search")
# def api_report_search(req: ReportSearchRequest) -> dict:
#     try:
#         return search_service(req.model_dump(exclude_none=True))
#     except WindowTooDeep as e:
#         raise HTTPException(status_code=400, detail=str(e))
#     except ValueError as e:
#         raise HTTPException(status_code=400, detail=str(e))


@router.post("/reports/search")
def api_report_search(req: ReportSearchRequest, user: ActiveUser) -> dict:
    try:
        # observe() 把这次请求记进 search_log（成功和失败都记），
        # 异常仍然原样抛出，下面的处理逻辑不受影响
        with search_log.observe(kind=history.KIND_REPORT, user_id=user.id,
                                req=req) as obs:
            result = search_service(req.model_dump(exclude_none=True))
            obs.ok(result_total=result.get("total"))
    except WindowTooDeep as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 记的是"一次检索"：翻页只会更新既有那行，不会新增（见 app/history/store.py）
    history.record_search(
        user_id=user.id,
        kind=history.KIND_REPORT,
        req=req,
        result_total=result.get("total"),
    )
    return result


# @router.get("/reports/{report_id}")
# def api_report_detail(report_id: str) -> dict:
#     report = get_report(report_id)
#     if report is None:
#         raise HTTPException(status_code=404, detail=f"report not found: {report_id}")
#     return report


@router.get("/reports/{report_id}")
def api_report_detail(report_id: str, user: ActiveUser) -> dict:
    report = get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"report not found: {report_id}")
    return report
