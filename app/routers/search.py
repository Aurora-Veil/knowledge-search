""" POST /api/v1/search """
from __future__ import annotations

import time
from typing import List, Literal, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth.deps import ActiveUser

from ..search.query import WindowTooDeep
from ..search.service import search as search_service

from ..history import store as history



router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchRequest(BaseModel):
    q: Optional[str] = None
    type: Literal["source", "evidence", "viewpoint", "all"] = "all"

    project_id: Optional[Union[int, List[int]]] = None

    # exact match
    status: Optional[str] = None
    presentation_type: Optional[str] = None
    period: Optional[str] = None             # presentation.period.keyword
    region: Optional[str] = None
    industry: Optional[str] = None
    source_type: Optional[Union[str, List[str]]] = None
    confidence_level: Optional[str] = None
    claim_type: Optional[str] = None
    applicable_scenario: Optional[str] = None
    cross_validation_mode: Optional[str] = None
    publisher: Optional[Union[str, List[str]]] = None 

    # responsibility[].operator.role
    responsible_role: Optional[str] = None

    # relation
    source_ids: Optional[List[str]] = None
    evidence_ids: Optional[List[str]] = None

    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    highlight: bool = True

    mode: Literal["or", "and", "phrase"] = "or"

# @router.post("/search")
# def api_search(req: SearchRequest) -> dict:
#     try:
#         return search_service(req.model_dump(exclude_none=True))
#     except WindowTooDeep as e:
#         # Paging this deep is not a server fault, but it cannot be served
#         # either: fusion reads page*size hits from every retriever.
#         raise HTTPException(status_code=400, detail=str(e))

@router.post("/search")
def api_search(req: SearchRequest, user: ActiveUser) -> dict:
    started = time.perf_counter()
    try:
        result = search_service(req.model_dump(exclude_none=True))
    except WindowTooDeep as e:
        raise HTTPException(status_code=400, detail=str(e))
    history.record_search(
        user_id=user.id,
        kind=history.KIND_OIRF,
        req=req,
        result_total=result.get("total"),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return result