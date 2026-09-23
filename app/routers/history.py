from __future__ import annotations

from typing import Any, Literal
from fastapi import APIRouter, HTTPException, Query

from ..auth.deps import ActiveUser
from ..history.store import UNAVAILABLE, list_history

router = APIRouter(prefix="/api/v1", tags=["history"])


@router.get("/history")
def api_history(
    user: ActiveUser,
    kind: Literal["oirf", "report"] | None = Query(None, description="None = All"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    try:
        return list_history(user.id, kind, limit)
    except UNAVAILABLE as e:
        raise HTTPException(status_code=503, detail="search history unavailable") from e
