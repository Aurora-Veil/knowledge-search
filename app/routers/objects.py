from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..search.objects import get_object as get_object_service

router = APIRouter(prefix="/api/v1", tags=["objects"])


@router.get("/objects/{object_type}/{oirf_id}")
def api_get_object(
    object_type: str,
    oirf_id: str,
    project_id: int = Query(..., description="project_id is required"),
) -> dict[str, Any]:
    try:
        obj = get_object_service(object_type, oirf_id, project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    return obj
