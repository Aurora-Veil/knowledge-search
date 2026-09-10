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

@router.post("/search")
def api_search(req: SearchRequest) -> dict:
    return search_service(req.model_dump(exclude_none=True))
