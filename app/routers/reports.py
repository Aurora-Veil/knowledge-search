""" POST /api/v1/reports/search  GET /api/v1/reports/{report_id} """
from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..search.query_reports import WindowTooDeep
from ..search.service_reports import get as get_report
from ..search.service_reports import search as search_service

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


@router.post("/reports/search")
def api_report_search(req: ReportSearchRequest) -> dict:
    try:
        return search_service(req.model_dump(exclude_none=True))
    except WindowTooDeep as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reports/{report_id}")
def api_report_detail(report_id: str) -> dict:
    report = get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"report not found: {report_id}")
    return report
