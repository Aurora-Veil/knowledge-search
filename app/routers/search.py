"""统一搜索入口 `POST /api/v1/search`（§5.1）。

- `type`：source | evidence | viewpoint | all（缺省 all）
- `project_id`：缺省 = 当前项目（config.DEFAULT_PROJECT_ID），显式传则跨项目（§5.0 定稿）
- 其余为精确筛选 / 关联参数，按类型感知映射到 keyword 字段（见 query.build_filters）
"""
from __future__ import annotations

from typing import List, Literal, Optional, Union

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import DEFAULT_PROJECT_ID
from ..search.service import search as search_service

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchRequest(BaseModel):
    q: Optional[str] = None                  # 全文检索词；空/缺省 = 仅过滤
    type: Literal["source", "evidence", "viewpoint", "all"] = "all"
    project_id: Optional[int] = None         # 缺省 = 当前项目

    # 精确筛选（进 bool.filter，命中 keyword 字段）
    status: Optional[str] = None
    presentation_type: Optional[str] = None
    period: Optional[str] = None             # 命中 presentation.period.keyword
    region: Optional[str] = None
    industry: Optional[str] = None
    source_type: Optional[Union[str, List[str]]] = None   # 单值或多值
    confidence_level: Optional[str] = None
    claim_type: Optional[str] = None
    applicable_scenario: Optional[str] = None
    cross_validation_mode: Optional[str] = None

    # 关联（类型感知：evidence 扁平 / viewpoint nested）
    responsible_role: Optional[str] = None
    source_ids: Optional[List[str]] = None
    evidence_ids: Optional[List[str]] = None

    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
    highlight: bool = True


@router.post("/search")
def api_search(req: SearchRequest) -> dict:
    p = req.model_dump(exclude_none=True)
    p.setdefault("project_id", DEFAULT_PROJECT_ID)  # 缺省当前项目，显式传覆盖
    return search_service(p)
