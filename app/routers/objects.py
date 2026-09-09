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
