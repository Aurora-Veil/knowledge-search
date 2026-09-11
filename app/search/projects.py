"""Project inventory: which project_id exist and how many objects each holds."""
from __future__ import annotations

from typing import Any

from ..config import COLLECTION_BY_TYPE
from ..db import get_db


def list_projects() -> dict[str, Any]:
    """
    Count objects per project_id.
    
    """
    db = get_db()
    project_ids: set[int] = set()
    for collection in COLLECTION_BY_TYPE.values():
        project_ids.update(int(pid) for pid in db[collection].distinct("project_id"))

    projects: list[dict[str, Any]] = []
    for pid in sorted(project_ids):
        per_type = {
            object_type: db[collection].count_documents({"project_id": pid})
            for object_type, collection in COLLECTION_BY_TYPE.items()
        }
        projects.append({
            "project_id": pid,
            "source": per_type.get("source", 0),
            "evidence": per_type.get("evidence", 0),
            "viewpoint": per_type.get("viewpoint", 0),
        })

    return {
        "projects": projects,
        "total_objects": sum(p["source"] + p["evidence"] + p["viewpoint"] for p in projects),
    }


__all__ = ["list_projects"]
