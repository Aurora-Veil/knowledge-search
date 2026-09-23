""" GET /api/v1/projects """
from __future__ import annotations

from fastapi import APIRouter

from ..auth.deps import ActiveUser
from ..search.projects import list_projects as list_projects_service

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects")
def api_list_projects(user: ActiveUser) -> dict:
    return list_projects_service()
