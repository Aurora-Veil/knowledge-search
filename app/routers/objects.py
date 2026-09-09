"""§5.2 完整对象端点：`GET /api/v1/objects/{object_type}/{oirf_id}?project_id=`。

`project_id` 缺省 = 当前项目（config.DEFAULT_PROJECT_ID），与 §5.0 定稿一致；显式传则跨项目。
必须限定 project_id（同号 oirf_id 跨项目会串号），否则串到别的项目。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from ..config import DEFAULT_PROJECT_ID
from ..search.objects import get_object as get_object_service

router = APIRouter(prefix="/api/v1", tags=["objects"])


@router.get("/objects/{object_type}/{oirf_id}")
def api_get_object(object_type: str, oirf_id: str, project_id: Optional[int] = None) -> dict[str, Any]:
    pid = project_id if project_id is not None else DEFAULT_PROJECT_ID
    try:
        obj = get_object_service(object_type, oirf_id, pid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    return obj
