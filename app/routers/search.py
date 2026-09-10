""" POST /api/v1/search """
from __future__ import annotations

from typing import List, Literal, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..search.service import search as search_service

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchRequest(BaseModel):
    q: Optional[str] = None
    type: Literal["source", "evidence", "viewpoint", "all"] = "all"
    # 全文匹配松紧（与 app/search/query.py 的 MATCH_MODES 保持一致）：
    #   or（默认，现状）任一命中 | and 所有词都要命中 | phrase 词必须相邻
    # q 为空时无意义（不产生全文子句）
    mode: Literal["or", "and", "phrase"] = "or"
    # 项目范围（都不传 = 全部项目，即全局检索）：
    #   project_id  = 单个项目；project_ids = 多项目并集；两者互斥
    project_id: Optional[int] = None
    project_ids: Optional[List[int]] = None

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

    # responsibility[].operator.role
    responsible_role: Optional[str] = None

    # relation
    source_ids: Optional[List[str]] = None
    evidence_ids: Optional[List[str]] = None

    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    highlight: bool = True


@router.post("/search")
def api_search(req: SearchRequest) -> dict:
    p = req.model_dump(exclude_none=True)
    if p.get("project_id") is not None and p.get("project_ids") is not None:
        raise HTTPException(status_code=400,
                            detail="project_id 与 project_ids 互斥：单项目用 project_id，多项目用 project_ids")
    if p.get("project_ids") == []:
        raise HTTPException(status_code=400,
                            detail="project_ids 不能是空数组：要全局检索就不传项目参数")
    # 不再补默认 project_id —— 缺省即「不加项目过滤」= 全局检索
    return search_service(p)
