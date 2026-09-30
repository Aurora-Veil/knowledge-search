""" GET /api/v1/associations/{object_type}/{oirf_id} """
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from ..auth.deps import ActiveUser
from ..config import OBJECT_TYPES
from ..search.associations import DEFAULT_LIMIT, MAX_HOPS, MAX_LIMIT, neighborhood

router = APIRouter(prefix="/api/v1", tags=["associations"])


@router.get("/associations/{object_type}/{oirf_id}")
def api_associations(
    object_type: Literal["source", "evidence", "viewpoint"],
    oirf_id: str,
    user: ActiveUser,
    # oirf_id unique in project → project_id required
    project_id: int = Query(..., description="project_id is required"),
    hops: int = Query(1, ge=1, le=MAX_HOPS, description="hops max = 2"),
    direction: Literal["out", "in", "both"] = "both",
    types: Optional[str] = Query(None, description="comma-separated subset of object types to filter"),
    include: Literal["card", "ref"] = "card",
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="bucket limit per (direction, type)"),
) -> dict:
    # 422: prefix mismatch / unknown types
    if oirf_id.split(":", 1)[0] != object_type:
        raise HTTPException(
            status_code=422,
            detail=f"oirf_id prefix must match object_type: got oirf_id={oirf_id!r} for object_type={object_type!r}",
        )

    types_set: Optional[set[str]] = None
    if types:
        items = [x.strip() for x in types.split(",") if x.strip()]
        unknown = [x for x in items if x not in OBJECT_TYPES]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown types: {unknown} (expected a subset of {list(OBJECT_TYPES)})",
            )
        types_set = set(items)

    result = neighborhood(
        object_type=object_type,
        oirf_id=oirf_id,
        project_id=project_id,
        hops=hops,
        direction=direction,
        types=types_set,
        include=include,
        limit=limit,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"{object_type} {oirf_id!r} not found in project {project_id}")
    return result
